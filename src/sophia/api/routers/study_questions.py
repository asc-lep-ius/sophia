"""Question generation and answer submission.

The two halves belong together: a question is persisted with the engagement
policy that gates it, and the attempt endpoint enforces exactly that policy
against the learner's own ingested event trace. Nothing the answering client
sends can relax it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from sophia.api.deps import get_app_container, get_settings, require_csrf_learning_path_scope
from sophia.api.provenance import api_provenance
from sophia.api.schemas.content import ContentLanguage
from sophia.api.schemas.engagement import ElaborationPolicy, LearningEventType
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.questions import OpenResponseQuestion, Question, QuestionDifficulty
from sophia.api.schemas.study import (
    StudyAttemptItemResponse,
    StudyAttemptRequest,
    StudyAttemptResponse,
    StudyQuestionListResponse,
    StudyQuestionRequest,
)
from sophia.domain.errors import AthenaError, EngagementPolicyUnmet
from sophia.domain.learning import ContentKind
from sophia.domain.learning import ContentLanguage as DomainContentLanguage
from sophia.services.content_language import resolve_content_language
from sophia.services.engagement_policy import evaluate_elaboration_policy
from sophia.services.learning_events import get_question_trace
from sophia.services.provenance import get_provenance_map
from sophia.services.study_questions import (
    default_elaboration_policy,
    generate_and_store_questions,
    get_question,
    save_attempt,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    import aiosqlite

    from sophia.domain.learning import ContentProvenance, GeneratedQuestion, QuestionAttempt
    from sophia.domain.learning import ElaborationPolicy as DomainElaborationPolicy

router = APIRouter(tags=["study"])

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
    await require_csrf_learning_path_scope(request, payload.learning_path_id)
    app_container = get_app_container(request)
    settings = get_settings(request)

    resolved = await resolve_content_language(
        app_container.db,
        payload.learning_path_id,
        override=None if lang is None else DomainContentLanguage(lang.value),
        default_language=DomainContentLanguage(settings.default_content_language),
    )
    questions = await generate_and_store_questions(
        app_container,
        payload.learning_path_id,
        payload.topic,
        count=payload.count,
        content_language=resolved.language,
        policy=default_elaboration_policy(
            min_elaboration_chars=settings.elaboration_min_chars,
            min_prompt_dwell_ms=settings.elaboration_min_prompt_dwell_ms,
        ),
    )
    provenance = await get_provenance_map(
        app_container.db,
        ContentKind.QUESTION,
        [question.id for question in questions],
    )
    return StudyQuestionListResponse(
        learning_path_id=payload.learning_path_id,
        topic=payload.topic,
        content_language=ContentLanguage(resolved.language.value),
        questions=[
            _question_response(question, _require_provenance(provenance, question))
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
    db = get_app_container(request).db

    question = await get_question(db, payload.question_id)
    if question is None or question.course_id != payload.learning_path_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    await _enforce_engagement_policy(db, question, session.user.id)
    attempt = await save_attempt(
        db,
        payload.learning_path_id,
        payload.question_id,
        session.user.id,
        payload.answer_text,
        payload.confidence,
    )
    return StudyAttemptResponse(attempt=_attempt_response(attempt))


async def _enforce_engagement_policy(
    db: aiosqlite.Connection,
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


def _question_response(
    question: GeneratedQuestion,
    provenance: ContentProvenance,
) -> Question:
    return OpenResponseQuestion(
        id=question.id,
        topic=question.topic,
        difficulty=QuestionDifficulty(question.difficulty),
        content_language=ContentLanguage(question.content_language.value),
        provenance=api_provenance(provenance),
        prompt=question.prompt,
        engagement_policy=_policy_response(question.elaboration_policy),
    )


def _require_provenance(
    provenance: Mapping[str, ContentProvenance],
    question: GeneratedQuestion,
) -> ContentProvenance:
    """Refuse to serve generated content whose provenance failed to persist.

    Silently dropping the question would hand the client a short list it cannot
    distinguish from a small one, and serving it without provenance would defeat
    the point of recording provenance at all.
    """
    record = provenance.get(question.id)
    if record is None:
        msg = f"generated question {question.id} has no provenance record"
        raise AthenaError(msg)
    return record


def _policy_response(policy: DomainElaborationPolicy | None) -> ElaborationPolicy:
    """Project a stored policy, or an ungated one for a question that carries none."""
    if policy is None:
        return ElaborationPolicy(
            required_event_types=[],
            min_elaboration_chars=0,
            min_prompt_dwell_ms=0,
        )
    return ElaborationPolicy(
        required_event_types=[
            LearningEventType(event_type.value) for event_type in policy.required_event_types
        ],
        min_elaboration_chars=policy.min_elaboration_chars,
        min_prompt_dwell_ms=policy.min_prompt_dwell_ms,
    )


def _attempt_response(attempt: QuestionAttempt) -> StudyAttemptItemResponse:
    return StudyAttemptItemResponse(
        id=attempt.id,
        learning_path_id=attempt.course_id,
        question_id=attempt.question_id,
        answer_text=attempt.answer_text,
        confidence=attempt.confidence,
        submitted_at=attempt.submitted_at,
    )
