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
from sophia.services.athena_session import (
    complete_study_session,
    get_study_sessions,
    save_flashcard,
    start_study_session,
)
from sophia.services.provenance import learner_authored, record_provenance

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.api.schemas.provenance import Provenance
    from sophia.domain.models import StudentFlashcard, StudySession

router = APIRouter(tags=["study"], route_class=TransactionalRoute)

ATHENA_SESSION_METHOD_COVERAGE: dict[str, dict[str, str]] = {
    "complete_study_session": {"operation_id": "completeStudySession"},
    "get_study_sessions": {"operation_id": "listStudySessions"},
    "run_interactive_session": {
        "rationale": "Rich/CLI orchestration is not a direct HTTP endpoint.",
    },
    "run_interleaved_session": {
        "rationale": "Rich/CLI orchestration is not a direct HTTP endpoint.",
    },
    "save_flashcard": {"operation_id": "saveStudyFlashcard"},
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
    await require_csrf_learning_path_scope(request, payload.learning_path_id)
    session = await start_study_session(
        await request_session(request),
        payload.learning_path_id,
        payload.topic,
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
    await require_csrf_learning_path_scope(request, payload.learning_path_id)
    db = await request_session(request)
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
