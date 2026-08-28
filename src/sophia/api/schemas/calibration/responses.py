"""Calibration API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel


class CalibrationRatingResponse(ApiModel):
    topic: str
    learning_path_id: int
    predicted: float
    actual: float | None
    rated_at: str
    calibration_error: float | None
    is_blind_spot: bool
    difficulty_level: str


class CalibrationRatingListResponse(ApiModel):
    learning_path_id: int
    ratings: list[CalibrationRatingResponse]


class CalibrationRatingSavedResponse(ApiModel):
    rating: CalibrationRatingResponse


class ActualScoreUpdateResponse(ApiModel):
    learning_path_id: int
    topic: str
    actual: float
    updated: bool
