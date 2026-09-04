"""Question generation and answer submission.

The two halves belong together: a question is persisted with the engagement
policy that gates it, and the attempt endpoint enforces exactly that policy
against the learner's own ingested event trace. Nothing the answering client
sends can relax it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from sophia.api.deps import (
    get_app_container,
    get_settings,
    request_session,
    require_csrf_learning_path_scope,
)
from sophia.api.questions import question_response, require_provenance
from sophia.api.schemas.content import ContentLanguage
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.study import (
    StudyAttemptItemResponse,
    StudyAttemptPhase,
    StudyAttemptRequest,
    StudyAttemptResponse,
    StudyQuestionListResponse,
    StudyQuestionRequest,
)
from sophia.api.transactions import TransactionalRoute
from sophia.domain.errors import EngagementPolicyUnmet
from sophia.domain.learning import AttemptPhase, ContentKind
from sophia.domain.learning import ContentLanguage as DomainContentLanguage
from sophia.services.athena_confidence import update_actual_score
from sophia.services.athena_session import get_session_scope
from sophia.services.content_language import resolve_content_language
from sophia.services.engagement_policy import evaluate_elaboration_policy
from sophia.services.learning_events import get_question_trace
from sophia.services.provenance import get_provenance_map
from sophia.services.study_events import append_event
from sophia.services.study_questions import (
    default_elaboration_policy,
    generate_and_store_questions,
    get_question,
    save_attempt,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.domain.learning import GeneratedQuestion, QuestionAttempt

router = APIRouter(tags=["study"], route_class=TransactionalRoute)

LanguageOverrideQuery = Annotated[ContentLanguage | None, Query(alias="lang")]


@router.post(
    "/study/questions",
    response_model=StudyQuestionListResponse,
    operation_id="generateStudyQuestions",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def generate_questions(
    payload: StudyQuestionRequest,
    request: Request,
    lang: LanguageOverrideQuery = None,
) -> StudyQuestionListResponse:
    session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    app_container = get_app_container(request)
    db = await request_session(request)
    settings = get_settings(request)

    if payload.session_id is not None:
        await _require_session_ownership(
            db, session.user.id, payload.learning_path_id, payload.session_id
        )

    resolved = await resolve_content_language(
        db,
        payload.learning_path_id,
        override=None if lang is None else DomainContentLanguage(lang.value),
        default_language=DomainContentLanguage(settings.default_content_language),
    )
    questions = await generate_and_store_questions(
        app_container,
        db,
        payload.learning_path_id,
        payload.topic,
        count=payload.count,
        content_language=resolved.language,
        policy=default_elaboration_policy(
            min_elaboration_chars=settings.elaboration_min_chars,
            min_prompt_dwell_ms=settings.elaboration_min_prompt_dwell_ms,
        ),
        user_id=session.user.id,
        session_id=payload.session_id,
    )
    provenance = await get_provenance_map(
        db,
        ContentKind.QUESTION,
        [question.id for question in questions],
    )
    return StudyQuestionListResponse(
        learning_path_id=payload.learning_path_id,
        topic=payload.topic,
        content_language=ContentLanguage(resolved.language.value),
        questions=[
            question_response(question, require_provenance(provenance, question))
            for question in questions
        ],
    )


@router.post(
    "/study/attempts",
    response_model=StudyAttemptResponse,
    operation_id="submitStudyAttempt",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_412_PRECONDITION_FAILED: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def submit_attempt(
    payload: StudyAttemptRequest,
    request: Request,
) -> StudyAttemptResponse:
    session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    db = await request_session(request)

    question = await get_question(db, payload.question_id)
    if question is None or question.course_id != payload.learning_path_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    await _require_session_ownership(
        db, session.user.id, payload.learning_path_id, payload.session_id
    )

    await _enforce_engagement_policy(db, question, session.user.id)
    result = await save_attempt(
        db,
        payload.learning_path_id,
        payload.question_id,
        session.user.id,
        payload.answer_text,
        payload.confidence,
        session_id=payload.session_id,
        request_id=payload.request_id,
        self_rating=payload.self_rating,
        phase=AttemptPhase(payload.phase.value),
    )
    if result.is_new:
        await update_actual_score(
            db,
            question.topic,
            question.course_id,
            result.attempt.score if result.attempt.score is not None else 0.0,
            user_id=session.user.id,
        )
        await append_event(
            db,
            session_id=payload.session_id,
            course_id=payload.learning_path_id,
            actor_id=session.user.id,
            event_type="attempt_scored",
            payload={
                "attempt_id": result.attempt.id,
                "question_id": payload.question_id,
                "score": result.attempt.score,
            },
            request_id=payload.request_id,
        )
    return StudyAttemptResponse(attempt=_attempt_response(result.attempt))


async def _require_session_ownership(
    db: AsyncSession,
    user_id: str,
    learning_path_id: int,
    session_id: int,
) -> None:
    """Answer 404, not 403, for somebody else's session: existence is not public."""
    scope = await get_session_scope(db, session_id)
    if scope is None or scope.course_id != learning_path_id or scope.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


async def _enforce_engagement_policy(
    db: AsyncSession,
    question: GeneratedQuestion,
    user_id: str,
) -> None:
    policy = question.elaboration_policy
    if policy is None:
        return

    trace = await get_question_trace(db, question.course_id, question.id, user_id)
    outcome = evaluate_elaboration_policy(policy, trace)
    if not outcome.met:
        msg = "answer submitted without the required learning process"
        raise EngagementPolicyUnmet(msg, outcome.params)


def _attempt_response(attempt: QuestionAttempt) -> StudyAttemptItemResponse:
    return StudyAttemptItemResponse(
        id=attempt.id,
        learning_path_id=attempt.course_id,
        session_id=attempt.session_id,
        question_id=attempt.question_id,
        answer_text=attempt.answer_text,
        confidence=attempt.confidence,
        self_rating=attempt.self_rating,
        score=attempt.score,
        phase=StudyAttemptPhase(attempt.phase.value),
        submitted_at=attempt.submitted_at,
    )
