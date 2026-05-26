"""Topics API request DTOs."""

from __future__ import annotations

from pydantic import Field

from sophia.api.schemas.common import ApiModel


class TopicExtractionRequest(ApiModel):
    module_id: int = Field(gt=0)
    force: bool = False


class ManualTopicRequest(ApiModel):
    course_id: int = Field(gt=0)
    topic: str = Field(min_length=1)


class TopicConfidenceRequest(ApiModel):
    course_id: int = Field(gt=0)
    topic: str = Field(min_length=1)
    rating: int = Field(ge=1, le=5)
