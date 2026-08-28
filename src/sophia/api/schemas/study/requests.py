"""Study API request DTOs."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class StudyFlashcardSource(StrEnum):
    """Where a flashcard came from, in source-agnostic terms."""

    STUDY = "study"
    TRANSCRIPT = "transcript"
    MANUAL = "manual"


class StudySessionStartRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    topic: str = Field(min_length=1)


class StudySessionCompleteRequest(ApiModel):
    pre_test_score: float = Field(ge=0.0, le=1.0)
    post_test_score: float = Field(ge=0.0, le=1.0)


class StudyFlashcardRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    topic: str = Field(min_length=1)
    front: str = Field(min_length=1)
    back: str = Field(min_length=1)
    source: StudyFlashcardSource = StudyFlashcardSource.STUDY


class StudyQuestionRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    topic: str = Field(min_length=1)
    count: int = Field(default=3, ge=1, le=10)


class StudyAttemptRequest(ApiModel):
    """A learner's answer to a previously generated question.

    The question is referenced by id rather than echoed back, so the engagement
    policy the server enforces is the one it issued, not one the client claims.
    """

    learning_path_id: int = Field(gt=0)
    question_id: str = Field(min_length=1, max_length=128)
    answer_text: str = Field(min_length=1)
    confidence: int | None = Field(default=None, ge=1, le=5)
