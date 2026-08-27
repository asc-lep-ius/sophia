"""Authenticated deadline current-state routes."""

from __future__ import annotations

from collections.abc import Mapping  # noqa: TC003
from typing import TYPE_CHECKING, Annotated, cast

from fastapi import APIRouter, HTTPException, Path, Query, Request, status

from sophia.api.deps import (
    current_session_record,
    ensure_course_scope,
    get_app_container,
    require_csrf,
    require_csrf_course_scope,
    require_effective_course_id,
)
from sophia.api.schemas.common import JsonPrimitive  # noqa: TC001
from sophia.api.schemas.deadlines import (
    DeadlineCompletionRequest,
    DeadlineCompletionResponse,
    DeadlineIcsExportResponse,
    DeadlineListResponse,
    DeadlineReflectionRequest,
    DeadlineReflectionResponse,
    DeadlineResponse,
    DeadlineSyncResponse,
    DeadlineTimeEntryRequest,
    DeadlineTimeEntryResponse,
    DeadlineTimerStartResponse,
    DeadlineTimerStopResponse,
    DeadlineTrackedTimeResponse,
    EffortEstimateRequest,
    EffortEstimateResponse,
    EffortEstimateSavedResponse,
    UpcomingExamListResponse,
    WorkloadDayResponse,
    WorkloadItemResponse,
    WorkloadResponse,
)
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

router = APIRouter(tags=["deadlines"])

LearningPathIdQuery = Annotated[int | None, Query(gt=0)]
DeadlineIdPath = Annotated[str, Path(min_length=1)]
DeadlineTypeQuery = Annotated[DeadlineType | None, Query()]
HorizonDaysQuery = Annotated[int, Query(ge=1, le=365)]

DbRow = tuple[object, ...]


@router.get(
    "/deadlines",
    response_model=DeadlineListResponse,
    operation_id="listDeadlines",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_deadlines(
    request: Request,
    learning_path_id: LearningPathIdQuery = None,
    horizon_days: HorizonDaysQuery = 14,
    deadline_type: DeadlineTypeQuery = None,
) -> DeadlineListResponse:
    effective_learning_path_id = await require_effective_course_id(request, learning_path_id)
    deadlines = await get_deadlines(
        get_app_container(request).db,
        course_id=effective_learning_path_id,
        horizon_days=horizon_days,
    )
    if deadline_type is not None:
        deadlines = [deadline for deadline in deadlines if deadline.deadline_type == deadline_type]
        if not deadlines:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return DeadlineListResponse(
        learning_path_id=effective_learning_path_id,
        horizon_days=horizon_days,
        deadlines=[_deadline_response(deadline) for deadline in deadlines],
    )


@router.post(
    "/deadlines/sync",
    response_model=DeadlineSyncResponse,
    operation_id="syncDeadlines",
)
async def sync_deadline_cache(request: Request) -> DeadlineSyncResponse:
    await require_csrf(request)
    effective_learning_path_id = await require_effective_course_id(request, None)
    deadlines = await sync_deadlines(get_app_container(request))
    scoped_deadlines = [
        deadline for deadline in deadlines if deadline.course_id == effective_learning_path_id
    ]
    return DeadlineSyncResponse(
        synced_count=len(scoped_deadlines),
        deadlines=[_deadline_response(deadline) for deadline in scoped_deadlines],
    )


@router.post(
    "/deadlines/estimates",
    response_model=EffortEstimateSavedResponse,
    operation_id="recordDeadlineEstimate",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def record_deadline_estimate(
    payload: EffortEstimateRequest,
    request: Request,
) -> EffortEstimateSavedResponse:
    app_container = await _require_csrf_payload_deadline_scope(
        request,
        payload.learning_path_id,
        payload.deadline_id,
    )
    estimate = await record_estimate(
        app_container,
        deadline_id=payload.deadline_id,
        course_id=payload.learning_path_id,
        predicted_hours=payload.predicted_hours,
        breakdown=payload.breakdown,
        intention=payload.intention,
    )
    return EffortEstimateSavedResponse(estimate=_estimate_response(estimate))


@router.post(
    "/deadlines/{deadline_id}/timer/start",
    response_model=DeadlineTimerStartResponse,
    operation_id="startDeadlineTimer",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def start_deadline_timer(
    deadline_id: DeadlineIdPath,
    request: Request,
) -> DeadlineTimerStartResponse:
    app_container, _course_id = await _require_csrf_deadline_scope(request, deadline_id)
    await start_timer(app_container.db, deadline_id)
    return DeadlineTimerStartResponse(deadline_id=deadline_id, started=True)


@router.post(
    "/deadlines/{deadline_id}/timer/stop",
    response_model=DeadlineTimerStopResponse,
    operation_id="stopDeadlineTimer",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def stop_deadline_timer(
    deadline_id: DeadlineIdPath,
    request: Request,
) -> DeadlineTimerStopResponse:
    app_container, _course_id = await _require_csrf_deadline_scope(request, deadline_id)
    elapsed_hours = await stop_timer(app_container.db, deadline_id)
    return DeadlineTimerStopResponse(deadline_id=deadline_id, elapsed_hours=elapsed_hours)


@router.get(
    "/deadlines/{deadline_id}/tracked-time",
    response_model=DeadlineTrackedTimeResponse,
    operation_id="getDeadlineTrackedTime",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def get_deadline_tracked_time(
    deadline_id: DeadlineIdPath,
    request: Request,
) -> DeadlineTrackedTimeResponse:
    app_container, _course_id = await _require_deadline_scope(request, deadline_id)
    total_hours = await get_tracked_time(app_container.db, deadline_id)
    return DeadlineTrackedTimeResponse(deadline_id=deadline_id, total_hours=total_hours)


@router.post(
    "/deadlines/time-entries",
    response_model=DeadlineTimeEntryResponse,
    operation_id="recordDeadlineTimeEntry",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def record_deadline_time_entry(
    payload: DeadlineTimeEntryRequest,
    request: Request,
) -> DeadlineTimeEntryResponse:
    app_container = await _require_csrf_payload_deadline_scope(
        request,
        payload.learning_path_id,
        payload.deadline_id,
    )
    await record_time(
        app_container.db,
        payload.deadline_id,
        payload.hours,
        payload.note,
        recorded_at=payload.recorded_at,
    )
    return DeadlineTimeEntryResponse(deadline_id=payload.deadline_id, recorded=True)


@router.post(
    "/deadlines/reflections",
    response_model=DeadlineReflectionResponse,
    operation_id="recordDeadlineReflection",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def record_deadline_reflection(
    payload: DeadlineReflectionRequest,
    request: Request,
) -> DeadlineReflectionResponse:
    app_container = await _require_csrf_payload_deadline_scope(
        request,
        payload.learning_path_id,
        payload.deadline_id,
    )
    await record_reflection(
        app_container.db,
        payload.deadline_id,
        predicted_hours=payload.predicted_hours,
        actual_hours=payload.actual_hours,
        reflection_text=payload.reflection_text,
    )
    return DeadlineReflectionResponse(deadline_id=payload.deadline_id, recorded=True)


@router.post(
    "/deadlines/{deadline_id}/complete",
    response_model=DeadlineCompletionResponse,
    operation_id="completeDeadline",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def complete_deadline_route(
    deadline_id: DeadlineIdPath,
    payload: DeadlineCompletionRequest,
    request: Request,
) -> DeadlineCompletionResponse:
    app_container = await _require_csrf_payload_deadline_scope(
        request,
        payload.learning_path_id,
        deadline_id,
    )
    predicted_hours, actual_hours, feedback = await complete_deadline(app_container, deadline_id)
    return DeadlineCompletionResponse(
        deadline_id=deadline_id,
        predicted_hours=predicted_hours,
        actual_hours=actual_hours,
        feedback=feedback,
        completed=True,
    )


@router.get(
    "/deadlines/workload",
    response_model=WorkloadResponse,
    operation_id="getDeadlineWorkload",
)
async def get_deadline_workload(
    request: Request,
    learning_path_id: LearningPathIdQuery = None,
    horizon_days: HorizonDaysQuery = 14,
) -> WorkloadResponse:
    effective_learning_path_id = await require_effective_course_id(request, learning_path_id)
    forecast = await get_workload_forecast(
        get_app_container(request).db,
        course_id=effective_learning_path_id,
        horizon_days=horizon_days,
    )
    return _workload_response(
        forecast,
        learning_path_id=effective_learning_path_id,
        horizon_days=horizon_days,
    )


@router.get(
    "/deadlines/upcoming-exams",
    response_model=UpcomingExamListResponse,
    operation_id="listUpcomingExams",
)
async def list_upcoming_exam_deadlines(
    request: Request,
    learning_path_id: LearningPathIdQuery = None,
    horizon_days: HorizonDaysQuery = 30,
) -> UpcomingExamListResponse:
    effective_learning_path_id = await require_effective_course_id(request, learning_path_id)
    exams = await get_upcoming_exams(
        get_app_container(request).db,
        course_id=effective_learning_path_id,
        horizon_days=horizon_days,
    )
    return UpcomingExamListResponse(
        learning_path_id=effective_learning_path_id,
        horizon_days=horizon_days,
        exams=[_deadline_response(exam) for exam in exams],
    )


@router.get(
    "/deadlines/ics",
    response_model=DeadlineIcsExportResponse,
    operation_id="exportDeadlinesIcs",
)
async def export_deadline_ics(
    request: Request,
    learning_path_id: LearningPathIdQuery = None,
    horizon_days: HorizonDaysQuery = 30,
) -> DeadlineIcsExportResponse:
    effective_learning_path_id = await require_effective_course_id(request, learning_path_id)
    ics = await export_deadlines_ics(
        get_app_container(request).db,
        course_id=effective_learning_path_id,
        horizon_days=horizon_days,
    )
    return DeadlineIcsExportResponse(
        learning_path_id=effective_learning_path_id,
        horizon_days=horizon_days,
        ics=ics,
    )


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
    payload_learning_path_id: int,
    deadline_id: str,
) -> AppContainer:
    session = await require_csrf_course_scope(request, payload_learning_path_id)
    app_container = get_app_container(request)
    course_id = await _deadline_course_id(app_container.db, deadline_id)
    if course_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    ensure_course_scope(session, course_id)
    if course_id != payload_learning_path_id:
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


def _deadline_response(deadline: Deadline) -> DeadlineResponse:
    return DeadlineResponse(
        id=deadline.id,
        name=deadline.name,
        learning_path_id=deadline.course_id,
        learning_path_name=deadline.course_name,
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


def _estimate_response(estimate: EffortEstimate) -> EffortEstimateResponse:
    return EffortEstimateResponse(
        deadline_id=estimate.deadline_id,
        learning_path_id=estimate.course_id,
        predicted_hours=estimate.predicted_hours,
        breakdown=estimate.breakdown,
        implementation_intention=estimate.implementation_intention,
        scaffold_level=estimate.scaffold_level.value,
        estimated_at=estimate.estimated_at,
    )


def _workload_response(
    forecast: Mapping[str, object],
    *,
    learning_path_id: int | None,
    horizon_days: int,
) -> WorkloadResponse:
    return WorkloadResponse(
        learning_path_id=learning_path_id,
        horizon_days=horizon_days,
        total_estimated_hours=_float_value(forecast.get("total_estimated_hours")),
        total_tracked_hours=_float_value(forecast.get("total_tracked_hours")),
        remaining_hours=_float_value(forecast.get("remaining_hours")),
        deadline_count=_int_value(forecast.get("deadline_count")),
        per_day=_workload_days(forecast.get("per_day")),
    )


def _workload_days(value: object) -> list[WorkloadDayResponse]:
    if not isinstance(value, dict):
        return []

    days: list[WorkloadDayResponse] = []
    for date_key, raw_items in cast("dict[object, object]", value).items():
        if not isinstance(date_key, str):
            continue
        days.append(
            WorkloadDayResponse(
                date=date_key,
                items=_workload_items(raw_items),
            )
        )
    return sorted(days, key=lambda day: day.date)


def _workload_items(raw_items: object) -> list[WorkloadItemResponse]:
    if not isinstance(raw_items, list):
        return []

    items: list[WorkloadItemResponse] = []
    for raw_item in cast("list[object]", raw_items):
        if not isinstance(raw_item, tuple):
            continue
        item = cast("tuple[object, ...]", raw_item)
        if len(item) < 2:
            continue
        name, hours = item[0], item[1]
        if isinstance(name, str):
            items.append(WorkloadItemResponse(name=name, hours=_float_value(hours)))
    return items


def _float_value(value: object) -> float:
    if isinstance(value, int | float | str):
        return float(value)
    return 0.0


def _int_value(value: object) -> int:
    if isinstance(value, int | float | str):
        return int(value)
    return 0
