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
    legacy_scored: bool


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


class CardConfidenceTopicResponse(ApiModel):
    """One topic's answers that carry a confidence, asked before each reveal."""

    topic: str
    rated: int
    sure: int
    sure_again: int


class CardConfidenceResponse(ApiModel):
    """How often an answer the learner was sure of met Again, per topic.

    ``unrated`` counts the answers given before cards asked for a confidence;
    they are left out of every topic rather than read as unsure.
    """

    learning_path_id: int
    topics: list[CardConfidenceTopicResponse]
    unrated: int
