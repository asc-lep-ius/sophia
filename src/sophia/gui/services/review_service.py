"""GUI-safe wrappers for athena spaced-repetition review scheduling.

Isolates the review page from direct service-layer imports and provides
pure helper functions for interval formatting and rating mapping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog

from sophia.services import athena_review
from sophia.services.athena_review import compute_fsrs_interval

if TYPE_CHECKING:
    import aiosqlite

    from sophia.domain.models import ReviewSchedule

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Rating constants
# ---------------------------------------------------------------------------

RATING_LABELS: Final[dict[int, str]] = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}
RATING_SCORES: Final[dict[int, float]] = {1: 0.0, 2: 0.3, 3: 0.7, 4: 1.0}

_VALID_RATINGS: Final = frozenset(RATING_SCORES)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def rating_to_score(rating: int) -> float:
    """Map a 1–4 button rating to an FSRS score float.

    Raises ``ValueError`` for ratings outside 1–4.
    """
    if rating not in _VALID_RATINGS:
        msg = f"Rating must be 1–4, got {rating}"
        raise ValueError(msg)
    return RATING_SCORES[rating]


def format_interval(days: int) -> str:
    """Human-readable interval string."""
    if days < 1:
        return "< 1 day"
    if days == 1:
        return "1 day"
    return f"{days} days"


def compute_interval_previews(difficulty: float, stability: float) -> dict[int, str]:
    """For each rating (1–4), compute and format the next review interval.

    Returns ``{1: "< 1 day", 2: "1 day", 3: "3 days", 4: "7 days"}`` (example).
    """
    previews: dict[int, str] = {}
    for rating, score in RATING_SCORES.items():
        _, _, interval_days = compute_fsrs_interval(difficulty, stability, score)
        previews[rating] = format_interval(interval_days)
    return previews


# ---------------------------------------------------------------------------
# Async wrappers
# ---------------------------------------------------------------------------


async def get_due_review_items(
    db: aiosqlite.Connection,
    *,
    course_id: int | None = None,
) -> list[ReviewSchedule]:
    """Fetch reviews that are currently due."""
    return await athena_review.get_due_reviews(db, course_id=course_id)


async def complete_review_item(
    db: aiosqlite.Connection,
    topic: str,
    course_id: int,
    score: float,
) -> ReviewSchedule:
    """Record a completed review and schedule the next one."""
    return await athena_review.complete_review(db, topic, course_id, score)


async def get_upcoming_review_items(
    db: aiosqlite.Connection,
    *,
    course_id: int | None = None,
    days_ahead: int = 3,
) -> list[ReviewSchedule]:
    """Fetch reviews due within the next *days_ahead* days."""
    return await athena_review.get_upcoming_reviews(db, course_id=course_id, days_ahead=days_ahead)
