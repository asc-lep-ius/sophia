"""Topics API response DTOs."""

from __future__ import annotations

from enum import StrEnum

from sophia.api.schemas.common import ApiModel


class TopicOrigin(StrEnum):
    """Where a topic mapping came from, in source-agnostic terms."""

    TRANSCRIPT = "transcript"
    QUIZ = "quiz"
    MANUAL = "manual"


class TopicMappingResponse(ApiModel):
    topic: str
    learning_path_id: int
    source: TopicOrigin
    frequency: int


class TopicListResponse(ApiModel):
    learning_path_id: int
    topics: list[TopicMappingResponse]


class TopicExtractionResponse(ApiModel):
    content_source_id: int
    topics: list[TopicMappingResponse]


class TopicResponse(ApiModel):
    topic: TopicMappingResponse


class TopicConfidenceRatingResponse(ApiModel):
    topic: str
    learning_path_id: int
    predicted: float
    actual: float | None
    rated_at: str
    calibration_error: float | None
    is_blind_spot: bool


class TopicConfidenceListResponse(ApiModel):
    learning_path_id: int
    ratings: list[TopicConfidenceRatingResponse]


class TopicConfidenceResponse(ApiModel):
    rating: TopicConfidenceRatingResponse
