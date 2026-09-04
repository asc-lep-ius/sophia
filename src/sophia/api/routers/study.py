"""Authenticated Athena study routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request, status
from sqlalchemy import select

from sophia.api.deps import (
    ensure_learning_path_scope,
    request_session,
    require_csrf,
    require_csrf_learning_path_scope,
    require_learning_path_scope,
)
from sophia.api.provenance import api_provenance
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.study import (
    StudyFlashcardItemResponse,
    StudyFlashcardRequest,
    StudyFlashcardResponse,
    StudyFlashcardSource,
    StudyPredictionItemResponse,
    StudyPredictionRequest,
    StudyPredictionResponse,
    StudyReflectionItemResponse,
    StudyReflectionRequest,
    StudyReflectionResponse,
    StudySelfExplanationItemResponse,
    StudySelfExplanationRequest,
    StudySelfExplanationResponse,
    StudySessionCompleteRequest,
    StudySessionCompletionResponse,
    StudySessionItemResponse,
    StudySessionListResponse,
    StudySessionResponse,
    StudySessionStartRequest,
)
from sophia.api.transactions import TransactionalRoute
from sophia.domain.learning import ContentKind
from sophia.domain.models import FlashcardSource
from sophia.infra.schema import study_sessions
from sophia.services.athena_confidence import record_study_prediction
from sophia.services.athena_session import (
    complete_study_session,
    get_flashcard_course_id,
    get_session_scope,
    get_study_sessions,
    save_flashcard,
    save_flashcard_idempotent,
    save_reflection,
    start_study_session,
)
from sophia.services.athena_study import save_self_explanation_idempotent
from sophia.services.provenance import learner_authored, record_provenance
from sophia.services.study_events import append_event

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.api.schemas.provenance import Provenance
    from sophia.api.sessions import SessionRecord
    from sophia.domain.models import (
        ConfidenceRating,
        SelfExplanation,
        StudentFlashcard,
        StudyReflection,
        StudySession,
    )

router = APIRouter(tags=["study"], route_class=TransactionalRoute)

ATHENA_SESSION_METHOD_COVERAGE: dict[str, dict[str, str]] = {
    "complete_study_session": {"operation_id": "completeStudySession"},
    "get_flashcard_course_id": {
        "rationale": "Scope-check lookup for the self-explanation endpoint, not itself a route.",
    },
    "get_session_scope": {
        "rationale": (
            "Ownership lookup shared by study.py, study_questions.py, and "
            "study_events.py's realtime endpoints — not itself an HTTP endpoint."
        ),
    },
    "get_study_sessions": {"operation_id": "listStudySessions"},
    "run_interactive_session": {
        "rationale": "Rich/CLI orchestration is not a direct HTTP endpoint.",
    },
    "run_interleaved_session": {
        "rationale": "Rich/CLI orchestration is not a direct HTTP endpoint.",
    },
    "save_flashcard": {"operation_id": "saveStudyFlashcard"},
    "save_flashcard_idempotent": {
        "rationale": (
            "The session-scoped idempotent variant saveStudyFlashcard uses when "
            "session_id/request_id are given — same operation, not a separate route."
        ),
    },
    "save_reflection": {"operation_id": "saveStudyReflection"},
    "start_study_session": {"operation_id": "startStudySession"},
}

_DOMAIN_FLASHCARD_SOURCE = {
    StudyFlashcardSource.STUDY: FlashcardSource.STUDY,
    StudyFlashcardSource.TRANSCRIPT: FlashcardSource.LECTURE,
    StudyFlashcardSource.MANUAL: FlashcardSource.MANUAL,
}
_API_FLASHCARD_SOURCE = {
    domain_source: api_source for api_source, domain_source in _DOMAIN_FLASHCARD_SOURCE.items()
}

LearningPathIdQuery = Annotated[int, Query(gt=0)]
SessionIdPath = Annotated[int, Path(gt=0)]
TopicFilterQuery = Annotated[str | None, Query(min_length=1)]


@router.get(
    "/study/sessions",
    response_model=StudySessionListResponse,
    operation_id="listStudySessions",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_study_sessions(
    learning_path_id: LearningPathIdQuery,
    request: Request,
    topic: TopicFilterQuery = None,
) -> StudySessionListResponse:
    await require_learning_path_scope(request, learning_path_id)
    sessions = await get_study_sessions(await request_session(request), learning_path_id, topic)
    if topic is not None and not sessions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return StudySessionListResponse(
        learning_path_id=learning_path_id,
        sessions=[_study_session_response(session) for session in sessions],
    )


@router.post(
    "/study/sessions",
    response_model=StudySessionResponse,
    operation_id="startStudySession",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def create_study_session(
    payload: StudySessionStartRequest,
    request: Request,
) -> StudySessionResponse:
    auth_session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    session = await start_study_session(
        await request_session(request),
        payload.learning_path_id,
        payload.topic,
        user_id=auth_session.user.id,
    )
    return StudySessionResponse(session=_study_session_response(session))


@router.post(
    "/study/sessions/{session_id}/complete",
    response_model=StudySessionCompletionResponse,
    operation_id="completeStudySession",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def mark_study_session_complete(
    session_id: SessionIdPath,
    payload: StudySessionCompleteRequest,
    request: Request,
) -> StudySessionCompletionResponse:
    auth_session = await require_csrf(request)
    db = await request_session(request)
    learning_path_id = await _study_session_learning_path_id(db, session_id)
    if learning_path_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    ensure_learning_path_scope(auth_session, learning_path_id)
    await complete_study_session(
        db,
        session_id,
        payload.pre_test_score,
        payload.post_test_score,
    )
    return StudySessionCompletionResponse(session_id=session_id, completed=True)


@router.post(
    "/study/flashcards",
    response_model=StudyFlashcardResponse,
    operation_id="saveStudyFlashcard",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def create_study_flashcard(
    payload: StudyFlashcardRequest,
    request: Request,
) -> StudyFlashcardResponse:
    auth_session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    db = await request_session(request)

    if payload.session_id is not None and payload.request_id is not None:
        await _require_session_ownership(
            db, auth_session, payload.learning_path_id, payload.session_id
        )
        flashcard, is_new = await save_flashcard_idempotent(
            db,
            payload.learning_path_id,
            payload.topic,
            payload.front,
            payload.back,
            _DOMAIN_FLASHCARD_SOURCE[payload.source].value,
            session_id=payload.session_id,
            user_id=auth_session.user.id,
            request_id=payload.request_id,
        )
        if is_new:
            await append_event(
                db,
                session_id=payload.session_id,
                course_id=payload.learning_path_id,
                actor_id=auth_session.user.id,
                event_type="flashcard_saved",
                payload={"flashcard_id": flashcard.id},
                request_id=payload.request_id,
            )
    else:
        flashcard = await save_flashcard(
            db,
            payload.learning_path_id,
            payload.topic,
            payload.front,
            payload.back,
            _DOMAIN_FLASHCARD_SOURCE[payload.source].value,
        )

    provenance = learner_authored(
        ContentKind.FLASHCARD,
        str(flashcard.id),
        flashcard.course_id,
        generated_at=flashcard.created_at,
    )
    await record_provenance(db, provenance)
    return StudyFlashcardResponse(
        flashcard=_flashcard_response(flashcard, api_provenance(provenance)),
    )


@router.post(
    "/study/predictions",
    response_model=StudyPredictionResponse,
    operation_id="recordStudyPrediction",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def create_study_prediction(
    payload: StudyPredictionRequest,
    request: Request,
) -> StudyPredictionResponse:
    auth_session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    db = await request_session(request)
    await _require_session_ownership(db, auth_session, payload.learning_path_id, payload.session_id)

    rating, is_new = await record_study_prediction(
        db,
        payload.topic,
        payload.learning_path_id,
        payload.rating,
        session_id=payload.session_id,
        user_id=auth_session.user.id,
        request_id=payload.request_id,
    )
    if is_new:
        await append_event(
            db,
            session_id=payload.session_id,
            course_id=payload.learning_path_id,
            actor_id=auth_session.user.id,
            event_type="prediction_recorded",
            payload={"topic": payload.topic, "predicted": rating.predicted},
            request_id=payload.request_id,
        )
    return StudyPredictionResponse(
        prediction=_prediction_response(rating, payload.learning_path_id)
    )


@router.post(
    "/study/self-explanations",
    response_model=StudySelfExplanationResponse,
    operation_id="saveStudySelfExplanation",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def create_self_explanation(
    payload: StudySelfExplanationRequest,
    request: Request,
) -> StudySelfExplanationResponse:
    auth_session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    db = await request_session(request)
    await _require_session_ownership(db, auth_session, payload.learning_path_id, payload.session_id)

    flashcard_course_id = await get_flashcard_course_id(db, payload.flashcard_id)
    if flashcard_course_id is None or flashcard_course_id != payload.learning_path_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    explanation, is_new = await save_self_explanation_idempotent(
        db,
        payload.flashcard_id,
        payload.student_explanation,
        payload.scaffold_level,
        session_id=payload.session_id,
        user_id=auth_session.user.id,
        request_id=payload.request_id,
    )
    if is_new:
        await append_event(
            db,
            session_id=payload.session_id,
            course_id=payload.learning_path_id,
            actor_id=auth_session.user.id,
            event_type="self_explanation_recorded",
            payload={"flashcard_id": explanation.flashcard_id},
            request_id=payload.request_id,
        )
    return StudySelfExplanationResponse(self_explanation=_self_explanation_response(explanation))


@router.post(
    "/study/reflections",
    response_model=StudyReflectionResponse,
    operation_id="saveStudyReflection",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def create_reflection(
    payload: StudyReflectionRequest,
    request: Request,
) -> StudyReflectionResponse:
    auth_session = await require_csrf_learning_path_scope(request, payload.learning_path_id)
    db = await request_session(request)
    await _require_session_ownership(db, auth_session, payload.learning_path_id, payload.session_id)

    reflection, is_new = await save_reflection(
        db,
        payload.session_id,
        payload.learning_path_id,
        auth_session.user.id,
        payload.prompt,
        payload.reflection_text,
        request_id=payload.request_id,
    )
    if is_new:
        await append_event(
            db,
            session_id=payload.session_id,
            course_id=payload.learning_path_id,
            actor_id=auth_session.user.id,
            event_type="reflection_recorded",
            payload={"prompt": payload.prompt},
            request_id=payload.request_id,
        )
    return StudyReflectionResponse(reflection=_reflection_response(reflection))


async def _require_session_ownership(
    db: AsyncSession,
    auth_session: SessionRecord,
    learning_path_id: int,
    session_id: int,
) -> None:
    """A session started before study realtime tracked ownership has no user_id
    to match, so it can never pass this check — see get_session_scope."""
    scope = await get_session_scope(db, session_id)
    if (
        scope is None
        or scope.course_id != learning_path_id
        or scope.user_id != auth_session.user.id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


async def _study_session_learning_path_id(
    db: AsyncSession,
    session_id: int,
) -> int | None:
    course_id = await db.scalar(
        select(study_sessions.c.course_id).where(study_sessions.c.id == session_id)
    )
    if course_id is None:
        return None
    if isinstance(course_id, int):
        return course_id
    if isinstance(course_id, str):
        return int(course_id)
    msg = "study session course_id must be an integer"
    raise TypeError(msg)


def _study_session_response(session: StudySession) -> StudySessionItemResponse:
    return StudySessionItemResponse(
        id=session.id,
        learning_path_id=session.course_id,
        topic=session.topic,
        pre_test_score=session.pre_test_score,
        post_test_score=session.post_test_score,
        started_at=session.started_at,
        completed_at=session.completed_at,
        improvement=session.improvement,
    )


def _flashcard_response(
    flashcard: StudentFlashcard,
    provenance: Provenance,
) -> StudyFlashcardItemResponse:
    return StudyFlashcardItemResponse(
        id=flashcard.id,
        learning_path_id=flashcard.course_id,
        topic=flashcard.topic,
        front=flashcard.front,
        back=flashcard.back,
        source=_API_FLASHCARD_SOURCE[flashcard.source],
        created_at=flashcard.created_at,
        provenance=provenance,
    )


def _prediction_response(
    rating: ConfidenceRating,
    learning_path_id: int,
) -> StudyPredictionItemResponse:
    return StudyPredictionItemResponse(
        learning_path_id=learning_path_id,
        topic=rating.topic,
        predicted=rating.predicted,
        rated_at=rating.rated_at,
    )


def _self_explanation_response(
    explanation: SelfExplanation,
) -> StudySelfExplanationItemResponse:
    return StudySelfExplanationItemResponse(
        id=explanation.id,
        flashcard_id=explanation.flashcard_id,
        student_explanation=explanation.student_explanation,
        scaffold_level=explanation.scaffold_level,
        created_at=explanation.created_at,
    )


def _reflection_response(reflection: StudyReflection) -> StudyReflectionItemResponse:
    return StudyReflectionItemResponse(
        id=reflection.id,
        session_id=reflection.session_id,
        learning_path_id=reflection.course_id,
        prompt=reflection.prompt,
        reflection_text=reflection.reflection_text,
        created_at=reflection.created_at,
    )
