"""Review API response DTOs."""

from __future__ import annotations

from sophia.api.schemas.common import ApiModel


class ReviewScheduleItemResponse(ApiModel):
    topic: str
    learning_path_id: int
    interval_index: int
    interval_days: int
    last_reviewed_at: str | None
    next_review_at: str
    score_at_last_review: float | None
    difficulty: float
    stability: float
    review_count: int
    is_due: bool


class DueReviewListResponse(ApiModel):
    # None when the list covers every course rather than one; each review
    # carries its own learning_path_id either way.
    learning_path_id: int | None
    reviews: list[ReviewScheduleItemResponse]


class UpcomingReviewListResponse(ApiModel):
    learning_path_id: int | None
    days_ahead: int
    reviews: list[ReviewScheduleItemResponse]


class ReviewScheduleListResponse(ApiModel):
    learning_path_id: int
    schedules: list[ReviewScheduleItemResponse]


class ReviewScheduleResponse(ApiModel):
    schedule: ReviewScheduleItemResponse
