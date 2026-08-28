"""Review API request DTOs."""

from __future__ import annotations

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class ReviewScheduleRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    topic: str = Field(min_length=1)


class ReviewCompletionRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    topic: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
