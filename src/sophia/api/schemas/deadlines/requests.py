"""Deadline API request DTOs."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from sophia.api.schemas.common import ApiModel

PositiveHours = Annotated[float, Field(gt=0.0)]


class EffortEstimateRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    deadline_id: str = Field(min_length=1)
    predicted_hours: PositiveHours
    breakdown: dict[str, PositiveHours] | None = None
    intention: str | None = Field(default=None, min_length=1)


class DeadlineTimeEntryRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    deadline_id: str = Field(min_length=1)
    hours: PositiveHours
    note: str | None = Field(default=None, min_length=1)
    recorded_at: str | None = Field(default=None, min_length=1)


class DeadlineReflectionRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
    deadline_id: str = Field(min_length=1)
    predicted_hours: PositiveHours | None = None
    actual_hours: PositiveHours
    reflection_text: str = Field(min_length=1)


class DeadlineCompletionRequest(ApiModel):
    learning_path_id: int = Field(gt=0)
