"""Study API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel
from sophia.api.schemas.content import ContentLanguage  # noqa: TC001
from sophia.api.schemas.provenance import Provenance  # noqa: TC001
from sophia.api.schemas.questions import Question  # noqa: TC001
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
    provenance: Provenance


class StudyFlashcardResponse(ApiModel):
    flashcard: StudyFlashcardItemResponse


class StudyQuestionListResponse(ApiModel):
    """Generated questions plus the language they were generated in."""

    learning_path_id: int
    topic: str
    content_language: ContentLanguage
    questions: list[Question]


class StudyAttemptItemResponse(ApiModel):
    id: int
    learning_path_id: int
    session_id: int | None
    question_id: str
    answer_text: str
    confidence: int | None
    self_rating: int | None
    score: float | None
    submitted_at: str


class StudyAttemptResponse(ApiModel):
    attempt: StudyAttemptItemResponse
