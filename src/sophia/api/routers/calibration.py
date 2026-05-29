"""Authenticated Athena calibration routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from sophia.api.deps import current_session_record, get_app_container, require_csrf
from sophia.api.schemas.calibration import (
    ActualScoreUpdateRequest,
    ActualScoreUpdateResponse,
    CalibrationRatingListResponse,
    CalibrationRatingRequest,
    CalibrationRatingResponse,
    CalibrationRatingSavedResponse,
)
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.services.athena_confidence import (
    get_blind_spots,
    get_confidence_ratings,
    get_topic_difficulty_level,
    rate_confidence,
    update_actual_score,
)

if TYPE_CHECKING:
    from sophia.domain.models import ConfidenceRating

router = APIRouter(tags=["calibration"])

ATHENA_CONFIDENCE_METHOD_COVERAGE: dict[str, dict[str, str]] = {
    "format_calibration_feedback": {
        "rationale": (
            "Presentation wording belongs to frontend formatting, not a standalone endpoint."
        ),
    },
    "get_blind_spots": {"operation_id": "listCalibrationBlindSpots"},
    "get_confidence_ratings": {"operation_id": "listCalibrationRatings"},
    "get_topic_difficulty_level": {
        "rationale": "Pure helper folded into calibration rating response DTOs.",
    },
    "rate_confidence": {"operation_id": "saveCalibrationConfidenceRating"},
    "rating_to_score": {
        "rationale": "Pure helper used inside rate_confidence, not a standalone HTTP concern.",
    },
    "update_actual_score": {"operation_id": "updateCalibrationActualScore"},
}

CourseIdQuery = Annotated[int, Query(gt=0)]
TopicFilterQuery = Annotated[str | None, Query(min_length=1)]


@router.get(
    "/calibration/ratings",
    response_model=CalibrationRatingListResponse,
    operation_id="listCalibrationRatings",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_calibration_ratings(
    course_id: CourseIdQuery,
    request: Request,
    topic: TopicFilterQuery = None,
) -> CalibrationRatingListResponse:
    await current_session_record(request)
    ratings = await get_confidence_ratings(get_app_container(request).db, course_id)
    if topic is not None:
        ratings = [rating for rating in ratings if rating.topic == topic]
        if not ratings:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return CalibrationRatingListResponse(
        course_id=course_id,
        ratings=[_calibration_rating_response(rating) for rating in ratings],
    )


@router.get(
    "/calibration/blind-spots",
    response_model=CalibrationRatingListResponse,
    operation_id="listCalibrationBlindSpots",
)
async def list_calibration_blind_spots(
    course_id: CourseIdQuery,
    request: Request,
) -> CalibrationRatingListResponse:
    await current_session_record(request)
    ratings = await get_blind_spots(get_app_container(request).db, course_id)
    return CalibrationRatingListResponse(
        course_id=course_id,
        ratings=[_calibration_rating_response(rating) for rating in ratings],
    )


@router.post(
    "/calibration/ratings",
    response_model=CalibrationRatingSavedResponse,
    operation_id="saveCalibrationConfidenceRating",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def save_calibration_rating(
    payload: CalibrationRatingRequest,
    request: Request,
) -> CalibrationRatingSavedResponse:
    await require_csrf(request)
    rating = await rate_confidence(
        get_app_container(request),
        payload.topic,
        payload.course_id,
        payload.rating,
    )
    return CalibrationRatingSavedResponse(rating=_calibration_rating_response(rating))


@router.patch(
    "/calibration/actual-score",
    response_model=ActualScoreUpdateResponse,
    operation_id="updateCalibrationActualScore",
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def patch_actual_score(
    payload: ActualScoreUpdateRequest,
    request: Request,
) -> ActualScoreUpdateResponse:
    await require_csrf(request)
    await update_actual_score(
        get_app_container(request).db,
        payload.topic,
        payload.course_id,
        payload.actual,
    )
    return ActualScoreUpdateResponse(
        course_id=payload.course_id,
        topic=payload.topic,
        actual=payload.actual,
        updated=True,
    )


def _calibration_rating_response(rating: ConfidenceRating) -> CalibrationRatingResponse:
    difficulty = get_topic_difficulty_level(rating.predicted)
    return CalibrationRatingResponse(
        topic=rating.topic,
        course_id=rating.course_id,
        predicted=rating.predicted,
        actual=rating.actual,
        rated_at=rating.rated_at,
        calibration_error=rating.calibration_error,
        is_blind_spot=rating.is_blind_spot,
        difficulty_level=difficulty.value,
    )
