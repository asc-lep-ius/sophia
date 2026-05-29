"""Study API request DTOs."""

from __future__ import annotations

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class StudySessionStartRequest(ApiModel):
    course_id: int = Field(gt=0)
    topic: str = Field(min_length=1)


class StudySessionCompleteRequest(ApiModel):
    pre_test_score: float = Field(ge=0.0, le=1.0)
    post_test_score: float = Field(ge=0.0, le=1.0)


class StudyFlashcardRequest(ApiModel):
    course_id: int = Field(gt=0)
    topic: str = Field(min_length=1)
    front: str = Field(min_length=1)
    back: str = Field(min_length=1)
    source: str = Field(default="study", min_length=1)
