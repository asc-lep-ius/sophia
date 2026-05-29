"""Authenticated Chronos history routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from sophia.api.deps import (
    current_session_record,
    ensure_course_scope,
    get_app_container,
    require_course_scope,
)
from sophia.api.schemas.chronos import ChronosCalibrationMetricResponse, ChronosDeadlineResponse
from sophia.api.schemas.chronos_history import (
    ChronosHistoryCalibrationResponse,
    ChronosHistoryDeadlineListResponse,
    ChronosHistoryEffortDayResponse,
    ChronosHistoryEffortDistributionResponse,
    ChronosHistoryReflectionItemResponse,
    ChronosHistoryReflectionResponse,
    ChronosHistoryTimeEntryListResponse,
    ChronosHistoryTimeEntryResponse,
)
from sophia.api.schemas.common import JsonPrimitive  # noqa: TC001
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.domain.models import Deadline  # noqa: TC001
from sophia.services.chronos_export import get_calibration_metrics
from sophia.services.chronos_history import (
    DayEffort,
    DeadlineReflection,
    TimeEntry,
    get_deadline_reflection,
    get_effort_distribution,
    get_past_deadlines,
    get_time_entries,
)

if TYPE_CHECKING:
    import aiosqlite

    from sophia.domain.models import CalibrationMetrics
    from sophia.infra.di import AppContainer

router = APIRouter(tags=["chronos-history"])

CourseIdQuery = Annotated[int | None, Query(gt=0)]
DeadlineIdPath = Annotated[str, Path(min_length=1)]
HorizonDaysQuery = Annotated[int, Query(ge=1, le=365)]
LimitQuery = Annotated[int, Query(ge=1, le=500)]

DbRow = tuple[object, ...]


@router.get(
    "/chronos-history/deadlines",
    response_model=ChronosHistoryDeadlineListResponse,
    operation_id="listChronosHistoryDeadlines",
)
async def list_chronos_history_deadlines(
    request: Request,
    course_id: CourseIdQuery = None,
    limit: LimitQuery = 50,
) -> ChronosHistoryDeadlineListResponse:
    await _require_optional_course_scope(request, course_id)
    deadlines = await get_past_deadlines(
        get_app_container(request).db,
        course_id=course_id,
        limit=limit,
    )
    return ChronosHistoryDeadlineListResponse(
        course_id=course_id,
        limit=limit,
        deadlines=[_deadline_response(deadline) for deadline in deadlines],
    )


@router.get(
    "/chronos-history/deadlines/{deadline_id}/reflection",
    response_model=ChronosHistoryReflectionResponse,
    operation_id="getChronosHistoryReflection",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def get_chronos_history_reflection(
    deadline_id: DeadlineIdPath,
    request: Request,
) -> ChronosHistoryReflectionResponse:
    app_container, _course_id = await _require_deadline_scope(request, deadline_id)
    reflection = await get_deadline_reflection(app_container.db, deadline_id)
    if reflection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return ChronosHistoryReflectionResponse(
        deadline_id=deadline_id,
        reflection=_reflection_response(reflection),
    )


@router.get(
    "/chronos-history/deadlines/{deadline_id}/time-entries",
    response_model=ChronosHistoryTimeEntryListResponse,
    operation_id="listChronosHistoryTimeEntries",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_chronos_history_time_entries(
    deadline_id: DeadlineIdPath,
    request: Request,
) -> ChronosHistoryTimeEntryListResponse:
    app_container, _course_id = await _require_deadline_scope(request, deadline_id)
    entries = await get_time_entries(app_container.db, deadline_id)
    return ChronosHistoryTimeEntryListResponse(
        deadline_id=deadline_id,
        entries=[_time_entry_response(entry) for entry in entries],
    )


@router.get(
    "/chronos-history/effort-distribution",
    response_model=ChronosHistoryEffortDistributionResponse,
    operation_id="getChronosHistoryEffortDistribution",
)
async def get_chronos_history_effort_distribution(
    request: Request,
    course_id: CourseIdQuery = None,
    horizon_days: HorizonDaysQuery = 14,
) -> ChronosHistoryEffortDistributionResponse:
    await _require_optional_course_scope(request, course_id)
    days = await get_effort_distribution(
        get_app_container(request).db,
        course_id=course_id,
        horizon_days=horizon_days,
    )
    return ChronosHistoryEffortDistributionResponse(
        course_id=course_id,
        horizon_days=horizon_days,
        days=[_effort_day_response(day) for day in days],
    )


@router.get(
    "/chronos-history/calibration",
    response_model=ChronosHistoryCalibrationResponse,
    operation_id="getChronosHistoryCalibration",
)
async def get_chronos_history_calibration(
    request: Request,
    course_id: CourseIdQuery = None,
) -> ChronosHistoryCalibrationResponse:
    await _require_optional_course_scope(request, course_id)
    metrics = await get_calibration_metrics(get_app_container(request).db, course_id=course_id)
    return ChronosHistoryCalibrationResponse(
        course_id=course_id,
        metrics=[_calibration_metric_response(metric) for metric in metrics],
    )


async def _require_optional_course_scope(request: Request, course_id: int | None) -> None:
    if course_id is None:
        await current_session_record(request)
        return
    await require_course_scope(request, course_id)


async def _require_deadline_scope(
    request: Request,
    deadline_id: str,
) -> tuple[AppContainer, int]:
    session = await current_session_record(request)
    app_container = get_app_container(request)
    course_id = await _deadline_course_id(app_container.db, deadline_id)
    if course_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    ensure_course_scope(session, course_id)
    return app_container, course_id


async def _deadline_course_id(db: aiosqlite.Connection, deadline_id: str) -> int | None:
    cursor = await db.execute("SELECT course_id FROM deadline_cache WHERE id = ?", (deadline_id,))
    row = cast("DbRow | None", await cursor.fetchone())
    if row is None:
        return None
    course_id = row[0]
    if isinstance(course_id, int):
        return course_id
    if isinstance(course_id, str):
        return int(course_id)
    msg = "deadline course_id must be an integer"
    raise TypeError(msg)


def _deadline_response(deadline: Deadline) -> ChronosDeadlineResponse:
    return ChronosDeadlineResponse(
        id=deadline.id,
        name=deadline.name,
        course_id=deadline.course_id,
        course_name=deadline.course_name,
        deadline_type=deadline.deadline_type.value,
        due_at=deadline.due_at,
        grade_weight=deadline.grade_weight,
        submission_status=deadline.submission_status,
        url=deadline.url,
        extra=_json_extra(cast("dict[str, object]", deadline.extra)),
    )


def _json_extra(extra: dict[str, object]) -> dict[str, JsonPrimitive]:
    safe_extra: dict[str, JsonPrimitive] = {}
    for key, value in extra.items():
        if value is None or isinstance(value, str | int | float | bool):
            safe_extra[key] = value
        else:
            safe_extra[key] = str(value)
    return safe_extra


def _reflection_response(
    reflection: DeadlineReflection,
) -> ChronosHistoryReflectionItemResponse:
    return ChronosHistoryReflectionItemResponse(
        predicted_hours=reflection.predicted_hours,
        actual_hours=reflection.actual_hours,
        reflection_text=reflection.reflection_text,
        reflected_at=reflection.reflected_at,
    )


def _time_entry_response(entry: TimeEntry) -> ChronosHistoryTimeEntryResponse:
    return ChronosHistoryTimeEntryResponse(
        hours=entry.hours,
        source=entry.source,
        note=entry.note,
        recorded_at=entry.recorded_at,
    )


def _effort_day_response(day: DayEffort) -> ChronosHistoryEffortDayResponse:
    return ChronosHistoryEffortDayResponse(
        date=day.date,
        deadline_efforts=day.deadline_efforts,
        unestimated=day.unestimated,
        total=day.total,
    )


def _calibration_metric_response(metric: CalibrationMetrics) -> ChronosCalibrationMetricResponse:
    return ChronosCalibrationMetricResponse(
        domain=metric.domain,
        sample_count=metric.sample_count,
        mean_error=metric.mean_error,
        mean_absolute_error=metric.mean_absolute_error,
        trend=metric.trend,
    )
