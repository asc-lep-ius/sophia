"""Study API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel
from sophia.api.schemas.study.requests import StudyFlashcardSource  # noqa: TC001


class StudySessionItemResponse(ApiModel):
    id: int
    learning_path_id: int
    topic: str
    pre_test_score: float | None
    post_test_score: float | None
    started_at: str
    completed_at: str | None
    improvement: float | None


class StudySessionListResponse(ApiModel):
    learning_path_id: int
    sessions: list[StudySessionItemResponse]


class StudySessionResponse(ApiModel):
    session: StudySessionItemResponse


class StudySessionCompletionResponse(ApiModel):
    session_id: int
    completed: bool


class StudyFlashcardItemResponse(ApiModel):
    id: int
    learning_path_id: int
    topic: str
    front: str
    back: str
    source: StudyFlashcardSource
    created_at: str


class StudyFlashcardResponse(ApiModel):
    flashcard: StudyFlashcardItemResponse
