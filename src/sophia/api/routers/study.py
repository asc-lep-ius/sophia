"""Authenticated Athena study routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from sophia.api.deps import current_session_record, get_app_container, require_csrf
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
    await current_session_record(request)
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
    await require_csrf(request)
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
    await require_csrf(request)
    await complete_study_session(
        get_app_container(request).db,
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
    await require_csrf(request)
    flashcard = await save_flashcard(
        get_app_container(request).db,
        payload.course_id,
        payload.topic,
        payload.front,
        payload.back,
        payload.source,
    )
    return StudyFlashcardResponse(flashcard=_flashcard_response(flashcard))


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
