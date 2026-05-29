"""Calibration API request DTOs."""

from __future__ import annotations

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class CalibrationRatingRequest(ApiModel):
    course_id: int = Field(gt=0)
    topic: str = Field(min_length=1)
    rating: int = Field(ge=1, le=5)


class ActualScoreUpdateRequest(ApiModel):
    course_id: int = Field(gt=0)
    topic: str = Field(min_length=1)
    actual: float = Field(ge=0.0, le=1.0)
