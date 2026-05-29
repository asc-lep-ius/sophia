"""Authenticated Athena review routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from sophia.api.deps import get_app_container, require_course_scope, require_csrf_course_scope
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.review import (
    DueReviewListResponse,
    ReviewCompletionRequest,
    ReviewScheduleItemResponse,
    ReviewScheduleListResponse,
    ReviewScheduleRequest,
    ReviewScheduleResponse,
    UpcomingReviewListResponse,
)
from sophia.services.athena_review import (
    complete_review,
    get_all_schedules,
    get_due_reviews,
    get_upcoming_reviews,
    schedule_review,
)

if TYPE_CHECKING:
    from sophia.domain.models import ReviewSchedule

router = APIRouter(tags=["review"])

CourseIdQuery = Annotated[int, Query(gt=0)]
DaysAheadQuery = Annotated[int, Query(ge=1, le=365)]
TopicFilterQuery = Annotated[str | None, Query(min_length=1)]


@router.get(
    "/review/due",
    response_model=DueReviewListResponse,
    operation_id="listDueReviews",
)
async def list_due_reviews(
    course_id: CourseIdQuery,
    request: Request,
) -> DueReviewListResponse:
    await require_course_scope(request, course_id)
    reviews = await get_due_reviews(get_app_container(request).db, course_id)
    return DueReviewListResponse(
        course_id=course_id,
        reviews=[_review_schedule_response(review) for review in reviews],
    )


@router.get(
    "/review/upcoming",
    response_model=UpcomingReviewListResponse,
    operation_id="listUpcomingReviews",
)
async def list_upcoming_reviews(
    course_id: CourseIdQuery,
    request: Request,
    days_ahead: DaysAheadQuery = 3,
) -> UpcomingReviewListResponse:
    await require_course_scope(request, course_id)
    reviews = await get_upcoming_reviews(
        get_app_container(request).db,
        course_id,
        days_ahead=days_ahead,
    )
    return UpcomingReviewListResponse(
        course_id=course_id,
        days_ahead=days_ahead,
        reviews=[_review_schedule_response(review) for review in reviews],
    )


@router.get(
    "/review/schedules",
    response_model=ReviewScheduleListResponse,
    operation_id="listReviewSchedules",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_review_schedules(
    course_id: CourseIdQuery,
    request: Request,
    topic: TopicFilterQuery = None,
) -> ReviewScheduleListResponse:
    await require_course_scope(request, course_id)
    schedules = await get_all_schedules(get_app_container(request).db, course_id)
    if topic is not None:
        schedules = [schedule for schedule in schedules if schedule.topic == topic]
        if not schedules:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return ReviewScheduleListResponse(
        course_id=course_id,
        schedules=[_review_schedule_response(schedule) for schedule in schedules],
    )


@router.post(
    "/review/schedules",
    response_model=ReviewScheduleResponse,
    operation_id="scheduleReview",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def create_review_schedule(
    payload: ReviewScheduleRequest,
    request: Request,
) -> ReviewScheduleResponse:
    await require_csrf_course_scope(request, payload.course_id)
    schedule = await schedule_review(
        get_app_container(request).db,
        payload.topic,
        payload.course_id,
    )
    return ReviewScheduleResponse(schedule=_review_schedule_response(schedule))


@router.post(
    "/review/complete",
    response_model=ReviewScheduleResponse,
    operation_id="completeReview",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def complete_review_schedule(
    payload: ReviewCompletionRequest,
    request: Request,
) -> ReviewScheduleResponse:
    await require_csrf_course_scope(request, payload.course_id)
    schedule = await complete_review(
        get_app_container(request).db,
        payload.topic,
        payload.course_id,
        payload.score,
    )
    return ReviewScheduleResponse(schedule=_review_schedule_response(schedule))


def _review_schedule_response(schedule: ReviewSchedule) -> ReviewScheduleItemResponse:
    return ReviewScheduleItemResponse(
        topic=schedule.topic,
        course_id=schedule.course_id,
        interval_index=schedule.interval_index,
        interval_days=schedule.interval_days,
        last_reviewed_at=schedule.last_reviewed_at,
        next_review_at=schedule.next_review_at,
        score_at_last_review=schedule.score_at_last_review,
        difficulty=schedule.difficulty,
        stability=schedule.stability,
        review_count=schedule.review_count,
        is_due=schedule.is_due,
    )
