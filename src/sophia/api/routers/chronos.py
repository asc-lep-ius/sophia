"""Authenticated Chronos current-state routes."""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from sophia.api.deps import (
    current_session_record,
    ensure_course_scope,
    get_app_container,
    require_course_scope,
    require_csrf,
    require_csrf_course_scope,
)
from sophia.api.schemas.chronos import (
    ChronosCompletionRequest,
    ChronosCompletionResponse,
    ChronosDeadlineListResponse,
    ChronosDeadlineResponse,
    ChronosEffortEstimateResponse,
    ChronosEstimateRequest,
    ChronosEstimateResponse,
    ChronosIcsExportResponse,
    ChronosReflectionRequest,
    ChronosReflectionResponse,
    ChronosSyncResponse,
    ChronosTimeEntryRequest,
    ChronosTimeEntryResponse,
    ChronosTimerStartResponse,
    ChronosTimerStopResponse,
    ChronosTrackedTimeResponse,
    ChronosUpcomingExamListResponse,
    ChronosWorkloadDayResponse,
    ChronosWorkloadItemResponse,
    ChronosWorkloadResponse,
)
from sophia.api.schemas.common import JsonPrimitive  # noqa: TC001
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.domain.models import Deadline, DeadlineType, EffortEstimate
from sophia.services.chronos import (
    complete_deadline,
    get_deadlines,
    get_tracked_time,
    get_workload_forecast,
    record_estimate,
    record_reflection,
    record_time,
    start_timer,
    stop_timer,
    sync_deadlines,
)
from sophia.services.chronos_export import export_deadlines_ics, get_upcoming_exams

if TYPE_CHECKING:
    import aiosqlite

    from sophia.infra.di import AppContainer

router = APIRouter(tags=["chronos"])

CourseIdQuery = Annotated[int | None, Query(gt=0)]
DeadlineIdPath = Annotated[str, Path(min_length=1)]
DeadlineTypeQuery = Annotated[DeadlineType | None, Query()]
HorizonDaysQuery = Annotated[int, Query(ge=1, le=365)]

DbRow = tuple[object, ...]


@router.get(
    "/chronos/deadlines",
    response_model=ChronosDeadlineListResponse,
    operation_id="listChronosDeadlines",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_chronos_deadlines(
    request: Request,
    course_id: CourseIdQuery = None,
    horizon_days: HorizonDaysQuery = 14,
    deadline_type: DeadlineTypeQuery = None,
) -> ChronosDeadlineListResponse:
    await _require_optional_course_scope(request, course_id)
    deadlines = await get_deadlines(
        get_app_container(request).db,
        course_id=course_id,
        horizon_days=horizon_days,
    )
    if deadline_type is not None:
        deadlines = [deadline for deadline in deadlines if deadline.deadline_type == deadline_type]
        if not deadlines:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return ChronosDeadlineListResponse(
        course_id=course_id,
        horizon_days=horizon_days,
        deadlines=[_deadline_response(deadline) for deadline in deadlines],
    )


@router.post(
    "/chronos/sync",
    response_model=ChronosSyncResponse,
    operation_id="syncChronosDeadlines",
)
async def sync_chronos_deadlines(request: Request) -> ChronosSyncResponse:
    await require_csrf(request)
    deadlines = await sync_deadlines(get_app_container(request))
    return ChronosSyncResponse(
        synced_count=len(deadlines),
        deadlines=[_deadline_response(deadline) for deadline in deadlines],
    )


@router.post(
    "/chronos/estimates",
    response_model=ChronosEstimateResponse,
    operation_id="recordChronosEstimate",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def record_chronos_estimate(
    payload: ChronosEstimateRequest,
    request: Request,
) -> ChronosEstimateResponse:
    await require_csrf_course_scope(request, payload.course_id)
    estimate = await record_estimate(
        get_app_container(request),
        deadline_id=payload.deadline_id,
        course_id=payload.course_id,
        predicted_hours=payload.predicted_hours,
        breakdown=payload.breakdown,
        intention=payload.intention,
    )
    return ChronosEstimateResponse(estimate=_estimate_response(estimate))


@router.post(
    "/chronos/timers/{deadline_id}/start",
    response_model=ChronosTimerStartResponse,
    operation_id="startChronosTimer",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def start_chronos_timer(
    deadline_id: DeadlineIdPath,
    request: Request,
) -> ChronosTimerStartResponse:
    app_container, _course_id = await _require_csrf_deadline_scope(request, deadline_id)
    await start_timer(app_container.db, deadline_id)
    return ChronosTimerStartResponse(deadline_id=deadline_id, started=True)


@router.post(
    "/chronos/timers/{deadline_id}/stop",
    response_model=ChronosTimerStopResponse,
    operation_id="stopChronosTimer",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def stop_chronos_timer(
    deadline_id: DeadlineIdPath,
    request: Request,
) -> ChronosTimerStopResponse:
    app_container, _course_id = await _require_csrf_deadline_scope(request, deadline_id)
    elapsed_hours = await stop_timer(app_container.db, deadline_id)
    return ChronosTimerStopResponse(deadline_id=deadline_id, elapsed_hours=elapsed_hours)


@router.get(
    "/chronos/deadlines/{deadline_id}/tracked-time",
    response_model=ChronosTrackedTimeResponse,
    operation_id="getChronosTrackedTime",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def get_chronos_tracked_time(
    deadline_id: DeadlineIdPath,
    request: Request,
) -> ChronosTrackedTimeResponse:
    app_container, _course_id = await _require_deadline_scope(request, deadline_id)
    total_hours = await get_tracked_time(app_container.db, deadline_id)
    return ChronosTrackedTimeResponse(deadline_id=deadline_id, total_hours=total_hours)


@router.post(
    "/chronos/time-entries",
    response_model=ChronosTimeEntryResponse,
    operation_id="recordChronosTimeEntry",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def record_chronos_time_entry(
    payload: ChronosTimeEntryRequest,
    request: Request,
) -> ChronosTimeEntryResponse:
    app_container = await _require_csrf_payload_deadline_scope(
        request,
        payload.course_id,
        payload.deadline_id,
    )
    await record_time(
        app_container.db,
        payload.deadline_id,
        payload.hours,
        payload.note,
        recorded_at=payload.recorded_at,
    )
    return ChronosTimeEntryResponse(deadline_id=payload.deadline_id, recorded=True)


@router.post(
    "/chronos/reflections",
    response_model=ChronosReflectionResponse,
    operation_id="recordChronosReflection",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def record_chronos_reflection(
    payload: ChronosReflectionRequest,
    request: Request,
) -> ChronosReflectionResponse:
    app_container = await _require_csrf_payload_deadline_scope(
        request,
        payload.course_id,
        payload.deadline_id,
    )
    await record_reflection(
        app_container.db,
        payload.deadline_id,
        predicted_hours=payload.predicted_hours,
        actual_hours=payload.actual_hours,
        reflection_text=payload.reflection_text,
    )
    return ChronosReflectionResponse(deadline_id=payload.deadline_id, recorded=True)


@router.post(
    "/chronos/deadlines/{deadline_id}/complete",
    response_model=ChronosCompletionResponse,
    operation_id="completeChronosDeadline",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def complete_chronos_deadline(
    deadline_id: DeadlineIdPath,
    payload: ChronosCompletionRequest,
    request: Request,
) -> ChronosCompletionResponse:
    app_container = await _require_csrf_payload_deadline_scope(
        request,
        payload.course_id,
        deadline_id,
    )
    predicted_hours, actual_hours, feedback = await complete_deadline(app_container, deadline_id)
    return ChronosCompletionResponse(
        deadline_id=deadline_id,
        predicted_hours=predicted_hours,
        actual_hours=actual_hours,
        feedback=feedback,
        completed=True,
    )


@router.get(
    "/chronos/workload",
    response_model=ChronosWorkloadResponse,
    operation_id="getChronosWorkload",
)
async def get_chronos_workload(
    request: Request,
    course_id: CourseIdQuery = None,
    horizon_days: HorizonDaysQuery = 14,
) -> ChronosWorkloadResponse:
    await _require_optional_course_scope(request, course_id)
    forecast = await get_workload_forecast(
        get_app_container(request).db,
        course_id=course_id,
        horizon_days=horizon_days,
    )
    return _workload_response(forecast, course_id=course_id, horizon_days=horizon_days)


@router.get(
    "/chronos/upcoming-exams",
    response_model=ChronosUpcomingExamListResponse,
    operation_id="listChronosUpcomingExams",
)
async def list_chronos_upcoming_exams(
    request: Request,
    course_id: CourseIdQuery = None,
    horizon_days: HorizonDaysQuery = 30,
) -> ChronosUpcomingExamListResponse:
    await _require_optional_course_scope(request, course_id)
    exams = await get_upcoming_exams(
        get_app_container(request).db,
        course_id=course_id,
        horizon_days=horizon_days,
    )
    return ChronosUpcomingExamListResponse(
        course_id=course_id,
        horizon_days=horizon_days,
        exams=[_deadline_response(exam) for exam in exams],
    )


@router.get(
    "/chronos/ics",
    response_model=ChronosIcsExportResponse,
    operation_id="exportChronosIcs",
)
async def export_chronos_ics(
    request: Request,
    course_id: CourseIdQuery = None,
    horizon_days: HorizonDaysQuery = 30,
) -> ChronosIcsExportResponse:
    await _require_optional_course_scope(request, course_id)
    ics = await export_deadlines_ics(
        get_app_container(request).db,
        course_id=course_id,
        horizon_days=horizon_days,
    )
    return ChronosIcsExportResponse(course_id=course_id, horizon_days=horizon_days, ics=ics)


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


async def _require_csrf_deadline_scope(
    request: Request,
    deadline_id: str,
) -> tuple[AppContainer, int]:
    session = await require_csrf(request)
    app_container = get_app_container(request)
    course_id = await _deadline_course_id(app_container.db, deadline_id)
    if course_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    ensure_course_scope(session, course_id)
    return app_container, course_id


async def _require_csrf_payload_deadline_scope(
    request: Request,
    payload_course_id: int,
    deadline_id: str,
) -> AppContainer:
    session = await require_csrf_course_scope(request, payload_course_id)
    app_container = get_app_container(request)
    course_id = await _deadline_course_id(app_container.db, deadline_id)
    if course_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    ensure_course_scope(session, course_id)
    if course_id != payload_course_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return app_container


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


def _estimate_response(estimate: EffortEstimate) -> ChronosEffortEstimateResponse:
    return ChronosEffortEstimateResponse(
        deadline_id=estimate.deadline_id,
        course_id=estimate.course_id,
        predicted_hours=estimate.predicted_hours,
        breakdown=estimate.breakdown,
        implementation_intention=estimate.implementation_intention,
        scaffold_level=estimate.scaffold_level.value,
        estimated_at=estimate.estimated_at,
    )


def _workload_response(
    forecast: Mapping[str, object],
    *,
    course_id: int | None,
    horizon_days: int,
) -> ChronosWorkloadResponse:
    return ChronosWorkloadResponse(
        course_id=course_id,
        horizon_days=horizon_days,
        total_estimated_hours=_float_value(forecast.get("total_estimated_hours")),
        total_tracked_hours=_float_value(forecast.get("total_tracked_hours")),
        remaining_hours=_float_value(forecast.get("remaining_hours")),
        deadline_count=_int_value(forecast.get("deadline_count")),
        per_day=_workload_days(forecast.get("per_day")),
    )


def _workload_days(value: object) -> list[ChronosWorkloadDayResponse]:
    if not isinstance(value, dict):
        return []

    days: list[ChronosWorkloadDayResponse] = []
    for date_key, raw_items in cast("dict[object, object]", value).items():
        if not isinstance(date_key, str):
            continue
        days.append(
            ChronosWorkloadDayResponse(
                date=date_key,
                items=_workload_items(raw_items),
            )
        )
    return sorted(days, key=lambda day: day.date)


def _workload_items(raw_items: object) -> list[ChronosWorkloadItemResponse]:
    if not isinstance(raw_items, list):
        return []

    items: list[ChronosWorkloadItemResponse] = []
    for raw_item in cast("list[object]", raw_items):
        if not isinstance(raw_item, tuple):
            continue
        item = cast("tuple[object, ...]", raw_item)
        if len(item) < 2:
            continue
        name, hours = item[0], item[1]
        if isinstance(name, str):
            items.append(ChronosWorkloadItemResponse(name=name, hours=_float_value(hours)))
    return items


def _float_value(value: object) -> float:
    if isinstance(value, int | float | str):
        return float(value)
    return 0.0


def _int_value(value: object) -> int:
    if isinstance(value, int | float | str):
        return int(value)
    return 0
