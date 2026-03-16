"""Athena spaced review scheduling service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from sophia.domain.models import REVIEW_INTERVALS, ReviewSchedule

if TYPE_CHECKING:
    import aiosqlite

log = structlog.get_logger()


def compute_next_interval(current_index: int, score: float) -> int:
    """Compute the next interval index based on review score.

    Score >= 0.8: advance to next interval
    Score 0.5-0.8: repeat current interval
    Score < 0.5: reset to first interval
    """
    if score >= 0.8:
        return min(current_index + 1, len(REVIEW_INTERVALS) - 1)
    if score >= 0.5:
        return current_index
    return 0


async def schedule_review(
    db: aiosqlite.Connection,
    topic: str,
    course_id: int,
) -> ReviewSchedule:
    """Create or reset a review schedule for a topic.

    Sets next_review_at to now + first interval (1 day).
    """
    now = datetime.now(UTC)
    next_at = (now + timedelta(days=REVIEW_INTERVALS[0])).isoformat()
    await db.execute(
        "INSERT INTO review_schedule (topic, course_id, interval_index, next_review_at) "
        "VALUES (?, ?, 0, ?) "
        "ON CONFLICT(topic, course_id) DO UPDATE SET "
        "interval_index = 0, next_review_at = excluded.next_review_at, "
        "last_reviewed_at = NULL, score_at_last_review = NULL",
        (topic, course_id, next_at),
    )
    await db.commit()
    return ReviewSchedule(
        topic=topic,
        course_id=course_id,
        interval_index=0,
        next_review_at=next_at,
    )


async def complete_review(
    db: aiosqlite.Connection,
    topic: str,
    course_id: int,
    score: float,
) -> ReviewSchedule:
    """Record a completed review and compute the next review date.

    Uses adaptive intervals:
    - score >= 0.8: advance interval (1->3->7->14->30 days)
    - 0.5 <= score < 0.8: repeat current interval
    - score < 0.5: reset to day 1
    """
    cursor = await db.execute(
        "SELECT interval_index FROM review_schedule WHERE topic = ? AND course_id = ?",
        (topic, course_id),
    )
    row = await cursor.fetchone()
    current_index = row[0] if row else 0

    new_index = compute_next_interval(current_index, score)
    now = datetime.now(UTC)
    interval_days = REVIEW_INTERVALS[min(new_index, len(REVIEW_INTERVALS) - 1)]
    next_at = (now + timedelta(days=interval_days)).isoformat()

    await db.execute(
        "INSERT INTO review_schedule (topic, course_id, interval_index, "
        "last_reviewed_at, next_review_at, score_at_last_review) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(topic, course_id) DO UPDATE SET "
        "interval_index = excluded.interval_index, "
        "last_reviewed_at = excluded.last_reviewed_at, "
        "next_review_at = excluded.next_review_at, "
        "score_at_last_review = excluded.score_at_last_review",
        (topic, course_id, new_index, now.isoformat(), next_at, score),
    )
    await db.commit()

    log.info("review_completed", topic=topic, score=score, next_interval=interval_days)
    return ReviewSchedule(
        topic=topic,
        course_id=course_id,
        interval_index=new_index,
        last_reviewed_at=now.isoformat(),
        next_review_at=next_at,
        score_at_last_review=score,
    )


def _rows_to_schedules(rows: list[Any]) -> list[ReviewSchedule]:
    return [
        ReviewSchedule(
            topic=row[0],
            course_id=row[1],
            interval_index=row[2],
            last_reviewed_at=row[3],
            next_review_at=row[4],
            score_at_last_review=row[5],
        )
        for row in rows
    ]


_SELECT_COLS = (
    "topic, course_id, interval_index, last_reviewed_at, next_review_at, score_at_last_review"
)


async def get_due_reviews(
    db: aiosqlite.Connection,
    course_id: int | None = None,
) -> list[ReviewSchedule]:
    """Get all topics that are due for review (next_review_at <= now).

    Optionally filter by course_id. Returns oldest-due first.
    """
    now = datetime.now(UTC).isoformat()
    if course_id is not None:
        cursor = await db.execute(
            f"SELECT {_SELECT_COLS} FROM review_schedule "
            "WHERE next_review_at <= ? AND course_id = ? ORDER BY next_review_at ASC",
            (now, course_id),
        )
    else:
        cursor = await db.execute(
            f"SELECT {_SELECT_COLS} FROM review_schedule "
            "WHERE next_review_at <= ? ORDER BY next_review_at ASC",
            (now,),
        )
    rows = list(await cursor.fetchall())
    return _rows_to_schedules(rows)


async def get_upcoming_reviews(
    db: aiosqlite.Connection,
    course_id: int | None = None,
    days_ahead: int = 3,
) -> list[ReviewSchedule]:
    """Get topics due within the next N days (but not yet due). Soonest first."""
    now = datetime.now(UTC)
    future = (now + timedelta(days=days_ahead)).isoformat()
    now_str = now.isoformat()
    if course_id is not None:
        cursor = await db.execute(
            f"SELECT {_SELECT_COLS} FROM review_schedule "
            "WHERE next_review_at > ? AND next_review_at <= ? AND course_id = ? "
            "ORDER BY next_review_at ASC",
            (now_str, future, course_id),
        )
    else:
        cursor = await db.execute(
            f"SELECT {_SELECT_COLS} FROM review_schedule "
            "WHERE next_review_at > ? AND next_review_at <= ? "
            "ORDER BY next_review_at ASC",
            (now_str, future),
        )
    rows = list(await cursor.fetchall())
    return _rows_to_schedules(rows)


async def get_all_schedules(
    db: aiosqlite.Connection,
    course_id: int,
) -> list[ReviewSchedule]:
    """Get all review schedules for a course."""
    cursor = await db.execute(
        f"SELECT {_SELECT_COLS} FROM review_schedule "
        "WHERE course_id = ? ORDER BY next_review_at ASC",
        (course_id,),
    )
    rows = list(await cursor.fetchall())
    return _rows_to_schedules(rows)
