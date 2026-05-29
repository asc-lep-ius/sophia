"""Authenticated Athena study routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from sophia.api.deps import (
    ensure_course_scope,
    get_app_container,
    require_course_scope,
    require_csrf,
    require_csrf_course_scope,
)
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.study import (
    StudyFlashcardItemResponse,
    StudyFlashcardRequest,
    StudyFlashcardResponse,
    StudySessionCompleteRequest,
    StudySessionCompletionResponse,
    StudySessionItemResponse,
    StudySessionListResponse,
    StudySessionResponse,
    StudySessionStartRequest,
)
from sophia.services.athena_session import (
    complete_study_session,
    get_study_sessions,
    save_flashcard,
    start_study_session,
)

if TYPE_CHECKING:
    import aiosqlite

    from sophia.domain.models import StudentFlashcard, StudySession

router = APIRouter(tags=["study"])

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

CourseIdQuery = Annotated[int, Query(gt=0)]
SessionIdPath = Annotated[int, Path(gt=0)]
TopicFilterQuery = Annotated[str | None, Query(min_length=1)]


@router.get(
    "/study/sessions",
    response_model=StudySessionListResponse,
    operation_id="listStudySessions",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_study_sessions(
    course_id: CourseIdQuery,
    request: Request,
    topic: TopicFilterQuery = None,
) -> StudySessionListResponse:
    await require_course_scope(request, course_id)
    sessions = await get_study_sessions(get_app_container(request).db, course_id, topic)
    if topic is not None and not sessions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return StudySessionListResponse(
        course_id=course_id,
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
    await require_csrf_course_scope(request, payload.course_id)
    session = await start_study_session(
        get_app_container(request).db,
        payload.course_id,
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
    session = await require_csrf(request)
    app_container = get_app_container(request)
    course_id = await _study_session_course_id(app_container.db, session_id)
    if course_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    ensure_course_scope(session, course_id)
    await complete_study_session(
        app_container.db,
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
    await require_csrf_course_scope(request, payload.course_id)
    flashcard = await save_flashcard(
        get_app_container(request).db,
        payload.course_id,
        payload.topic,
        payload.front,
        payload.back,
        payload.source.value,
    )
    return StudyFlashcardResponse(flashcard=_flashcard_response(flashcard))


async def _study_session_course_id(
    db: aiosqlite.Connection,
    session_id: int,
) -> int | None:
    cursor = await db.execute("SELECT course_id FROM study_sessions WHERE id = ?", (session_id,))
    row = cast("tuple[object, ...] | None", await cursor.fetchone())
    if row is None:
        return None
    course_id = row[0]
    if isinstance(course_id, int):
        return course_id
    if isinstance(course_id, str):
        return int(course_id)
    msg = "study session course_id must be an integer"
    raise TypeError(msg)


def _study_session_response(session: StudySession) -> StudySessionItemResponse:
    return StudySessionItemResponse(
        id=session.id,
        course_id=session.course_id,
        topic=session.topic,
        pre_test_score=session.pre_test_score,
        post_test_score=session.post_test_score,
        started_at=session.started_at,
        completed_at=session.completed_at,
        improvement=session.improvement,
    )


def _flashcard_response(flashcard: StudentFlashcard) -> StudyFlashcardItemResponse:
    return StudyFlashcardItemResponse(
        id=flashcard.id,
        course_id=flashcard.course_id,
        topic=flashcard.topic,
        front=flashcard.front,
        back=flashcard.back,
        source=flashcard.source.value,
        created_at=flashcard.created_at,
    )
