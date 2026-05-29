"""Study API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel


class StudySessionItemResponse(ApiModel):
    id: int
    course_id: int
    topic: str
    pre_test_score: float | None
    post_test_score: float | None
    started_at: str
    completed_at: str | None
    improvement: float | None


class StudySessionListResponse(ApiModel):
    course_id: int
    sessions: list[StudySessionItemResponse]


class StudySessionResponse(ApiModel):
    session: StudySessionItemResponse


class StudySessionCompletionResponse(ApiModel):
    session_id: int
    completed: bool


class StudyFlashcardItemResponse(ApiModel):
    id: int
    course_id: int
    topic: str
    front: str
    back: str
    source: str
    created_at: str


class StudyFlashcardResponse(ApiModel):
    flashcard: StudyFlashcardItemResponse
