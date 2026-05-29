"""Chronos API response DTOs."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from pydantic import Field

from sophia.api.schemas.common import ApiModel, JsonPrimitive


class ChronosDeadlineResponse(ApiModel):
    id: str
    name: str
    course_id: int
    course_name: str
    deadline_type: str
    due_at: datetime
    grade_weight: float | None
    submission_status: str | None
    url: str | None
    extra: dict[str, JsonPrimitive] = Field(default_factory=dict)


class ChronosDeadlineListResponse(ApiModel):
    course_id: int | None
    horizon_days: int
    deadlines: list[ChronosDeadlineResponse]


class ChronosSyncResponse(ApiModel):
    synced_count: int
    deadlines: list[ChronosDeadlineResponse]


class ChronosEffortEstimateResponse(ApiModel):
    deadline_id: str
    course_id: int
    predicted_hours: float
    breakdown: dict[str, float] | None
    implementation_intention: str | None
    scaffold_level: str
    estimated_at: str


class ChronosEstimateResponse(ApiModel):
    estimate: ChronosEffortEstimateResponse


class ChronosTimerStartResponse(ApiModel):
    deadline_id: str
    started: bool


class ChronosTimerStopResponse(ApiModel):
    deadline_id: str
    elapsed_hours: float


class ChronosTrackedTimeResponse(ApiModel):
    deadline_id: str
    total_hours: float


class ChronosTimeEntryResponse(ApiModel):
    deadline_id: str
    recorded: bool


class ChronosReflectionResponse(ApiModel):
    deadline_id: str
    recorded: bool


class ChronosCompletionResponse(ApiModel):
    deadline_id: str
    predicted_hours: float | None
    actual_hours: float
    feedback: str
    completed: bool


class ChronosWorkloadItemResponse(ApiModel):
    name: str
    hours: float


class ChronosWorkloadDayResponse(ApiModel):
    date: str
    items: list[ChronosWorkloadItemResponse]


class ChronosWorkloadResponse(ApiModel):
    course_id: int | None
    horizon_days: int
    total_estimated_hours: float
    total_tracked_hours: float
    remaining_hours: float
    deadline_count: int
    per_day: list[ChronosWorkloadDayResponse]


class ChronosUpcomingExamListResponse(ApiModel):
    course_id: int | None
    horizon_days: int
    exams: list[ChronosDeadlineResponse]


class ChronosIcsExportResponse(ApiModel):
    course_id: int | None
    horizon_days: int
    ics: str


class ChronosCalibrationMetricResponse(ApiModel):
    domain: str
    sample_count: int
    mean_error: float
    mean_absolute_error: float
    trend: str
