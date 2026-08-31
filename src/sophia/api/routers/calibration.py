"""Authenticated Athena calibration routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status

from sophia.api.deps import (
    request_session,
    require_csrf_learning_path_scope,
    require_learning_path_scope,
)
from sophia.api.schemas.calibration import (
    ActualScoreUpdateRequest,
    ActualScoreUpdateResponse,
    CalibrationRatingListResponse,
    CalibrationRatingRequest,
    CalibrationRatingResponse,
    CalibrationRatingSavedResponse,
)
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.transactions import TransactionalRoute
from sophia.services.athena_confidence import (
    get_blind_spots,
    get_confidence_ratings,
    get_topic_difficulty_level,
    rate_confidence,
    update_actual_score,
)

if TYPE_CHECKING:
    from sophia.domain.models import ConfidenceRating

router = APIRouter(tags=["calibration"], route_class=TransactionalRoute)

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

LearningPathIdQuery = Annotated[int, Query(gt=0)]
TopicFilterQuery = Annotated[str | None, Query(min_length=1)]


@router.get(
    "/calibration/ratings",
    response_model=CalibrationRatingListResponse,
    operation_id="listCalibrationRatings",
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorEnvelope}},
)
async def list_calibration_ratings(
    learning_path_id: LearningPathIdQuery,
    request: Request,
    topic: TopicFilterQuery = None,
) -> CalibrationRatingListResponse:
    await require_learning_path_scope(request, learning_path_id)
    ratings = await get_confidence_ratings(await request_session(request), learning_path_id)
    if topic is not None:
        ratings = [rating for rating in ratings if rating.topic == topic]
        if not ratings:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return CalibrationRatingListResponse(
        learning_path_id=learning_path_id,
        ratings=[_calibration_rating_response(rating) for rating in ratings],
    )


@router.get(
    "/calibration/blind-spots",
    response_model=CalibrationRatingListResponse,
    operation_id="listCalibrationBlindSpots",
)
async def list_calibration_blind_spots(
    learning_path_id: LearningPathIdQuery,
    request: Request,
) -> CalibrationRatingListResponse:
    await require_learning_path_scope(request, learning_path_id)
    ratings = await get_blind_spots(await request_session(request), learning_path_id)
    return CalibrationRatingListResponse(
        learning_path_id=learning_path_id,
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
    await require_csrf_learning_path_scope(request, payload.learning_path_id)
    rating = await rate_confidence(
        await request_session(request),
        payload.topic,
        payload.learning_path_id,
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
    await require_csrf_learning_path_scope(request, payload.learning_path_id)
    await update_actual_score(
        await request_session(request),
        payload.topic,
        payload.learning_path_id,
        payload.actual,
    )
    return ActualScoreUpdateResponse(
        learning_path_id=payload.learning_path_id,
        topic=payload.topic,
        actual=payload.actual,
        updated=True,
    )


def _calibration_rating_response(rating: ConfidenceRating) -> CalibrationRatingResponse:
    difficulty = get_topic_difficulty_level(rating.predicted)
    return CalibrationRatingResponse(
        topic=rating.topic,
        learning_path_id=rating.course_id,
        predicted=rating.predicted,
        actual=rating.actual,
        rated_at=rating.rated_at,
        calibration_error=rating.calibration_error,
        is_blind_spot=rating.is_blind_spot,
        difficulty_level=difficulty.value,
    )
