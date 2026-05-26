"""Topics API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel


class TopicMappingResponse(ApiModel):
    topic: str
    course_id: int
    source: str
    frequency: int


class TopicListResponse(ApiModel):
    course_id: int
    topics: list[TopicMappingResponse]


class TopicExtractionResponse(ApiModel):
    module_id: int
    topics: list[TopicMappingResponse]


class TopicResponse(ApiModel):
    topic: TopicMappingResponse


class TopicConfidenceRatingResponse(ApiModel):
    topic: str
    course_id: int
    predicted: float
    actual: float | None
    rated_at: str
    calibration_error: float | None
    is_blind_spot: bool


class TopicConfidenceListResponse(ApiModel):
    course_id: int
    ratings: list[TopicConfidenceRatingResponse]


class TopicConfidenceResponse(ApiModel):
    rating: TopicConfidenceRatingResponse
