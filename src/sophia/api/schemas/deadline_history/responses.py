"""Deadline history API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel
from sophia.api.schemas.deadlines import (  # noqa: TC001
    DeadlineResponse,
    EffortCalibrationMetricResponse,
)


class PastDeadlineListResponse(ApiModel):
    learning_path_id: int | None
    limit: int
    deadlines: list[DeadlineResponse]


class DeadlineReflectionItemResponse(ApiModel):
    predicted_hours: float | None
    actual_hours: float
    reflection_text: str | None
    reflected_at: str


class DeadlineReflectionDetailResponse(ApiModel):
    deadline_id: str
    reflection: DeadlineReflectionItemResponse


class DeadlineTimeEntryItemResponse(ApiModel):
    hours: float
    source: str
    note: str | None
    recorded_at: str


class DeadlineTimeEntryListResponse(ApiModel):
    deadline_id: str
    entries: list[DeadlineTimeEntryItemResponse]


class EffortDayResponse(ApiModel):
    date: str
    deadline_efforts: dict[str, float]
    unestimated: list[str]
    total: float


class EffortDistributionResponse(ApiModel):
    learning_path_id: int | None
    horizon_days: int
    days: list[EffortDayResponse]


class EffortCalibrationResponse(ApiModel):
    learning_path_id: int | None
    metrics: list[EffortCalibrationMetricResponse]
