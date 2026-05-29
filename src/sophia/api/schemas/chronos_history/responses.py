"""Chronos history API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.chronos import (  # noqa: TC001
    ChronosCalibrationMetricResponse,
    ChronosDeadlineResponse,
)
from sophia.api.schemas.common import ApiModel


class ChronosHistoryDeadlineListResponse(ApiModel):
    course_id: int | None
    limit: int
    deadlines: list[ChronosDeadlineResponse]


class ChronosHistoryReflectionItemResponse(ApiModel):
    predicted_hours: float | None
    actual_hours: float
    reflection_text: str | None
    reflected_at: str


class ChronosHistoryReflectionResponse(ApiModel):
    deadline_id: str
    reflection: ChronosHistoryReflectionItemResponse


class ChronosHistoryTimeEntryResponse(ApiModel):
    hours: float
    source: str
    note: str | None
    recorded_at: str


class ChronosHistoryTimeEntryListResponse(ApiModel):
    deadline_id: str
    entries: list[ChronosHistoryTimeEntryResponse]


class ChronosHistoryEffortDayResponse(ApiModel):
    date: str
    deadline_efforts: dict[str, float]
    unestimated: list[str]
    total: float


class ChronosHistoryEffortDistributionResponse(ApiModel):
    course_id: int | None
    horizon_days: int
    days: list[ChronosHistoryEffortDayResponse]


class ChronosHistoryCalibrationResponse(ApiModel):
    course_id: int | None
    metrics: list[ChronosCalibrationMetricResponse]
