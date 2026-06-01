"""Authenticated quickstart routes."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query, Request, status

from sophia.api.deps import (
    get_app_container,
    require_csrf_course_scope,
    require_effective_course_id,
)
from sophia.api.schemas.chronos import ChronosDeadlineResponse
from sophia.api.schemas.common import JsonPrimitive  # noqa: TC001
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.quickstart import (
    QuickstartConfidenceRequest,
    QuickstartConfidenceResponse,
    QuickstartCourseResponse,
    QuickstartManualTopicsRequest,
    QuickstartManualTopicsResponse,
    QuickstartOverviewResponse,
    QuickstartSessionCountResponse,
    QuickstartTopicResponse,
)
from sophia.domain.models import Course, Deadline, TopicMapping  # noqa: TC001
from sophia.services.quickstart import (
    QuickstartOverview,
    get_completed_session_count,
    get_quickstart_overview,
    save_initial_confidence,
    save_manual_topics,
)

router = APIRouter(tags=["quickstart"])

CourseIdQuery = Annotated[int | None, Query(gt=0)]


@router.get(
    "/quickstart/overview",
    response_model=QuickstartOverviewResponse,
    operation_id="getQuickstartOverview",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def get_quickstart_overview_route(
    request: Request,
    course_id: CourseIdQuery = None,
) -> QuickstartOverviewResponse:
    effective_course_id = await require_effective_course_id(request, course_id)
    overview = await get_quickstart_overview(
        get_app_container(request),
        course_id=effective_course_id,
    )
    if not overview.courses:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _overview_response(overview, course_id=effective_course_id)


@router.post(
    "/quickstart/confidence",
    response_model=QuickstartConfidenceResponse,
    operation_id="saveQuickstartConfidence",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def save_quickstart_confidence(
    payload: QuickstartConfidenceRequest,
    request: Request,
) -> QuickstartConfidenceResponse:
    await require_csrf_course_scope(request, payload.course_id)
    saved_count = await save_initial_confidence(
        get_app_container(request),
        course_id=payload.course_id,
        ratings=payload.ratings,
    )
    return QuickstartConfidenceResponse(course_id=payload.course_id, saved_count=saved_count)


@router.post(
    "/quickstart/manual-topics",
    response_model=QuickstartManualTopicsResponse,
    operation_id="saveQuickstartManualTopics",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def save_quickstart_manual_topics(
    payload: QuickstartManualTopicsRequest,
    request: Request,
) -> QuickstartManualTopicsResponse:
    await require_csrf_course_scope(request, payload.course_id)
    topics = await save_manual_topics(
        get_app_container(request),
        course_id=payload.course_id,
        topics=payload.topics,
    )
    return QuickstartManualTopicsResponse(
        course_id=payload.course_id,
        topics=[_topic_response(topic) for topic in topics],
    )


@router.get(
    "/quickstart/session-count",
    response_model=QuickstartSessionCountResponse,
    operation_id="getQuickstartSessionCount",
)
async def get_quickstart_session_count(
    request: Request,
    course_id: CourseIdQuery = None,
) -> QuickstartSessionCountResponse:
    effective_course_id = await require_effective_course_id(request, course_id)
    completed_session_count = await get_completed_session_count(
        get_app_container(request),
        course_id=effective_course_id,
    )
    return QuickstartSessionCountResponse(
        course_id=effective_course_id,
        completed_session_count=completed_session_count,
    )


def _overview_response(
    overview: QuickstartOverview,
    *,
    course_id: int | None,
) -> QuickstartOverviewResponse:
    return QuickstartOverviewResponse(
        course_id=course_id,
        courses=[_course_response(course) for course in overview.courses],
        topics=[_topic_response(topic) for topic in overview.topics],
        nearest_deadline=(
            _deadline_response(overview.nearest_deadline)
            if overview.nearest_deadline is not None
            else None
        ),
        completed_session_count=overview.completed_session_count,
    )


def _course_response(course: Course) -> QuickstartCourseResponse:
    return QuickstartCourseResponse(
        id=course.id,
        fullname=course.fullname,
        shortname=course.shortname,
        url=course.url,
    )


def _topic_response(topic: TopicMapping) -> QuickstartTopicResponse:
    return QuickstartTopicResponse(
        topic=topic.topic,
        course_id=topic.course_id,
        source=topic.source.value,
        frequency=topic.frequency,
    )


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
