"""Deadline API response DTOs."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003

from pydantic import Field

from sophia.api.schemas.common import ApiModel, JsonPrimitive


class DeadlineResponse(ApiModel):
    id: str
    name: str
    learning_path_id: int
    learning_path_name: str
    deadline_type: str
    due_at: datetime
    grade_weight: float | None
    submission_status: str | None
    url: str | None
    extra: dict[str, JsonPrimitive] = Field(default_factory=dict)


class DeadlineListResponse(ApiModel):
    learning_path_id: int | None
    horizon_days: int
    deadlines: list[DeadlineResponse]


class DeadlineSyncResponse(ApiModel):
    synced_count: int
    deadlines: list[DeadlineResponse]


class EffortEstimateResponse(ApiModel):
    deadline_id: str
    learning_path_id: int
    predicted_hours: float
    breakdown: dict[str, float] | None
    implementation_intention: str | None
    scaffold_level: str
    estimated_at: str


class EffortEstimateSavedResponse(ApiModel):
    estimate: EffortEstimateResponse


class DeadlineTimerStartResponse(ApiModel):
    deadline_id: str
    started: bool


class DeadlineTimerStopResponse(ApiModel):
    deadline_id: str
    elapsed_hours: float


class DeadlineTrackedTimeResponse(ApiModel):
    deadline_id: str
    total_hours: float


class DeadlineTimeEntryResponse(ApiModel):
    deadline_id: str
    recorded: bool


class DeadlineReflectionResponse(ApiModel):
    deadline_id: str
    recorded: bool


class DeadlineCompletionResponse(ApiModel):
    deadline_id: str
    predicted_hours: float | None
    actual_hours: float
    feedback: str
    completed: bool


class WorkloadItemResponse(ApiModel):
    name: str
    hours: float


class WorkloadDayResponse(ApiModel):
    date: str
    items: list[WorkloadItemResponse]


class WorkloadResponse(ApiModel):
    learning_path_id: int | None
    horizon_days: int
    total_estimated_hours: float
    total_tracked_hours: float
    remaining_hours: float
    deadline_count: int
    per_day: list[WorkloadDayResponse]


class UpcomingExamListResponse(ApiModel):
    learning_path_id: int | None
    horizon_days: int
    exams: list[DeadlineResponse]


class DeadlineIcsExportResponse(ApiModel):
    learning_path_id: int | None
    horizon_days: int
    ics: str


class EffortCalibrationMetricResponse(ApiModel):
    domain: str
    sample_count: int
    mean_error: float
    mean_absolute_error: float
    trend: str
