"""Quickstart API request DTOs."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from sophia.api.schemas.common import ApiModel

ConfidenceRatingValue = Annotated[int, Field(ge=1, le=5)]
ManualTopic = Annotated[str, Field(min_length=1)]


class QuickstartConfidenceRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    ratings: dict[str, ConfidenceRatingValue] = Field(min_length=1)


class QuickstartManualTopicsRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    topics: list[ManualTopic] = Field(min_length=1)
