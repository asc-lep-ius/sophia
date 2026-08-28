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
