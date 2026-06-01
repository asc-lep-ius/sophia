"""Authenticated Athena topic and confidence routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from sophia.api.deps import get_app_container, require_course_scope, require_csrf_course_scope
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.topics import (
    ManualTopicRequest,
    TopicConfidenceListResponse,
    TopicConfidenceRatingResponse,
    TopicConfidenceRequest,
    TopicConfidenceResponse,
    TopicExtractionRequest,
    TopicExtractionResponse,
    TopicListResponse,
    TopicMappingResponse,
    TopicResponse,
)
from sophia.services.athena_confidence import get_confidence_ratings, rate_confidence
from sophia.services.athena_study import (
    extract_topics_from_lectures,
    get_course_topics,
    save_manual_topic,
)

if TYPE_CHECKING:
    from sophia.domain.models import ConfidenceRating, TopicMapping

router = APIRouter(tags=["topics"])

CourseIdQuery = Annotated[int, Query(gt=0)]
TopicFilterQuery = Annotated[str | None, Query(min_length=1)]


@router.get(
    "/topics",
    response_model=TopicListResponse,
    operation_id="listTopics",
)
async def list_topics(
    course_id: CourseIdQuery,
    request: Request,
) -> TopicListResponse:
    await require_course_scope(request, course_id)
    topics = await get_course_topics(get_app_container(request), course_id)
    return TopicListResponse(
        course_id=course_id, topics=[_topic_response(topic) for topic in topics]
    )


@router.post(
    "/topics/extract",
    response_model=TopicExtractionResponse,
    operation_id="extractTopics",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def extract_topics(
    payload: TopicExtractionRequest,
    request: Request,
) -> TopicExtractionResponse:
    await require_csrf_course_scope(request, payload.module_id)
    topics = await extract_topics_from_lectures(
        get_app_container(request),
        payload.module_id,
        force=payload.force,
    )
    return TopicExtractionResponse(
        module_id=payload.module_id,
        topics=[_topic_response(topic) for topic in topics],
    )


@router.post(
    "/topics/manual",
    response_model=TopicResponse,
    operation_id="saveManualTopic",
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope},
    },
)
async def create_manual_topic(
    payload: ManualTopicRequest,
    request: Request,
) -> TopicResponse:
    await require_csrf_course_scope(request, payload.course_id)
    topic = await save_manual_topic(get_app_container(request), payload.topic, payload.course_id)
    if topic is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return TopicResponse(topic=_topic_response(topic))


@router.get(
    "/topics/confidence",
    response_model=TopicConfidenceListResponse,
    operation_id="listTopicConfidenceRatings",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_topic_confidence_ratings(
    course_id: CourseIdQuery,
    request: Request,
    topic: TopicFilterQuery = None,
) -> TopicConfidenceListResponse:
    await require_course_scope(request, course_id)
    ratings = await get_confidence_ratings(get_app_container(request).db, course_id)
    if topic is not None:
        ratings = [rating for rating in ratings if rating.topic == topic]
        if not ratings:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return TopicConfidenceListResponse(
        course_id=course_id,
        ratings=[_confidence_response(rating) for rating in ratings],
    )


@router.post(
    "/topics/confidence",
    response_model=TopicConfidenceResponse,
    operation_id="saveTopicConfidenceRating",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def save_topic_confidence_rating(
    payload: TopicConfidenceRequest,
    request: Request,
) -> TopicConfidenceResponse:
    await require_csrf_course_scope(request, payload.course_id)
    rating = await rate_confidence(
        get_app_container(request),
        payload.topic,
        payload.course_id,
        payload.rating,
    )
    return TopicConfidenceResponse(rating=_confidence_response(rating))


def _topic_response(topic: TopicMapping) -> TopicMappingResponse:
    return TopicMappingResponse(
        topic=topic.topic,
        course_id=topic.course_id,
        source=topic.source.value,
        frequency=topic.frequency,
    )


def _confidence_response(rating: ConfidenceRating) -> TopicConfidenceRatingResponse:
    return TopicConfidenceRatingResponse(
        topic=rating.topic,
        course_id=rating.course_id,
        predicted=rating.predicted,
        actual=rating.actual,
        rated_at=rating.rated_at,
        calibration_error=rating.calibration_error,
        is_blind_spot=rating.is_blind_spot,
    )
