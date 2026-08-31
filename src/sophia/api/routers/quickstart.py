"""Authenticated quickstart routes."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query, Request, status

from sophia.api.deps import (
    get_app_container,
    request_session,
    require_csrf_learning_path_scope,
    require_effective_learning_path_id,
)
from sophia.api.schemas.common import JsonPrimitive  # noqa: TC001
from sophia.api.schemas.deadlines import DeadlineResponse
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.quickstart import (
    QuickstartConfidenceRequest,
    QuickstartConfidenceResponse,
    QuickstartLearningPathResponse,
    QuickstartManualTopicsRequest,
    QuickstartManualTopicsResponse,
    QuickstartOverviewResponse,
    QuickstartSessionCountResponse,
    QuickstartTopicResponse,
)
from sophia.api.schemas.topics import TopicOrigin
from sophia.api.transactions import TransactionalRoute
from sophia.domain.models import Course, Deadline, TopicMapping, TopicSource  # noqa: TC001
from sophia.services.quickstart import (
    QuickstartOverview,
    get_completed_session_count,
    get_quickstart_overview,
    save_initial_confidence,
    save_manual_topics,
)

router = APIRouter(tags=["quickstart"], route_class=TransactionalRoute)

_TOPIC_ORIGIN_BY_SOURCE = {
    TopicSource.LECTURE: TopicOrigin.TRANSCRIPT,
    TopicSource.QUIZ: TopicOrigin.QUIZ,
    TopicSource.MANUAL: TopicOrigin.MANUAL,
}

LearningPathIdQuery = Annotated[int | None, Query(gt=0)]


@router.get(
    "/quickstart/overview",
    response_model=QuickstartOverviewResponse,
    operation_id="getQuickstartOverview",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def get_quickstart_overview_route(
    request: Request,
    learning_path_id: LearningPathIdQuery = None,
) -> QuickstartOverviewResponse:
    effective_learning_path_id = await require_effective_learning_path_id(request, learning_path_id)
    overview = await get_quickstart_overview(
        get_app_container(request),
        await request_session(request),
        course_id=effective_learning_path_id,
    )
    if not overview.courses:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _overview_response(overview, learning_path_id=effective_learning_path_id)


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
    await require_csrf_learning_path_scope(request, payload.learning_path_id)
    saved_count = await save_initial_confidence(
        await request_session(request),
        course_id=payload.learning_path_id,
        ratings=payload.ratings,
    )
    return QuickstartConfidenceResponse(
        learning_path_id=payload.learning_path_id,
        saved_count=saved_count,
    )


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
    await require_csrf_learning_path_scope(request, payload.learning_path_id)
    topics = await save_manual_topics(
        await request_session(request),
        course_id=payload.learning_path_id,
        topics=payload.topics,
    )
    return QuickstartManualTopicsResponse(
        learning_path_id=payload.learning_path_id,
        topics=[_topic_response(topic) for topic in topics],
    )


@router.get(
    "/quickstart/session-count",
    response_model=QuickstartSessionCountResponse,
    operation_id="getQuickstartSessionCount",
)
async def get_quickstart_session_count(
    request: Request,
    learning_path_id: LearningPathIdQuery = None,
) -> QuickstartSessionCountResponse:
    effective_learning_path_id = await require_effective_learning_path_id(request, learning_path_id)
    completed_session_count = await get_completed_session_count(
        await request_session(request),
        course_id=effective_learning_path_id,
    )
    return QuickstartSessionCountResponse(
        learning_path_id=effective_learning_path_id,
        completed_session_count=completed_session_count,
    )


def _overview_response(
    overview: QuickstartOverview,
    *,
    learning_path_id: int | None,
) -> QuickstartOverviewResponse:
    return QuickstartOverviewResponse(
        learning_path_id=learning_path_id,
        learning_paths=[_learning_path_response(course) for course in overview.courses],
        topics=[_topic_response(topic) for topic in overview.topics],
        nearest_deadline=(
            _deadline_response(overview.nearest_deadline)
            if overview.nearest_deadline is not None
            else None
        ),
        completed_session_count=overview.completed_session_count,
    )


def _learning_path_response(course: Course) -> QuickstartLearningPathResponse:
    return QuickstartLearningPathResponse(
        id=course.id,
        title=course.fullname,
        short_title=course.shortname,
        url=course.url,
    )


def _topic_response(topic: TopicMapping) -> QuickstartTopicResponse:
    return QuickstartTopicResponse(
        topic=topic.topic,
        learning_path_id=topic.course_id,
        source=_TOPIC_ORIGIN_BY_SOURCE[topic.source],
        frequency=topic.frequency,
    )


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
