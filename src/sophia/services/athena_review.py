"""Athena spaced review scheduling service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from sophia.domain.models import REVIEW_INTERVALS, ReviewSchedule

if TYPE_CHECKING:
    import aiosqlite

log = structlog.get_logger()


# FSRS default parameters
FSRS_DEFAULT_DIFFICULTY = 0.3
FSRS_DEFAULT_STABILITY = 1.0


def compute_fsrs_interval(
    difficulty: float,
    stability: float,
    score: float,
) -> tuple[float, float, int]:
    """Compute next FSRS parameters.

    Returns (new_difficulty, new_stability, interval_days).
    """
    new_difficulty = max(0.1, min(1.0, difficulty + 0.1 * (1 - score) - 0.05))

    if score >= 0.5:
        stability_multiplier = 2.5 * (1 - new_difficulty) * (score + 0.1)
        new_stability = max(0.5, stability * stability_multiplier)
    else:
        new_stability = max(0.5, stability * 0.3)

    new_stability = min(new_stability, 365.0)
    interval_days = max(1, round(new_stability))
    return (new_difficulty, new_stability, interval_days)


async def schedule_review(
    db: aiosqlite.Connection,
    topic: str,
    course_id: int,
) -> ReviewSchedule:
    """Create or reset a review schedule for a topic.

    Sets next_review_at to now + first interval (1 day).
    Initializes FSRS columns with defaults.
    """
    now = datetime.now(UTC)
    next_at = (now + timedelta(days=REVIEW_INTERVALS[0])).isoformat()
    await db.execute(
        "INSERT INTO review_schedule "
        "(topic, course_id, interval_index, next_review_at, "
        "difficulty, stability, review_count) "
        "VALUES (?, ?, 0, ?, ?, ?, 0) "
        "ON CONFLICT(topic, course_id) DO UPDATE SET "
        "interval_index = 0, next_review_at = excluded.next_review_at, "
        "last_reviewed_at = NULL, score_at_last_review = NULL, "
        "difficulty = excluded.difficulty, stability = excluded.stability, "
        "review_count = 0",
        (topic, course_id, next_at, FSRS_DEFAULT_DIFFICULTY, FSRS_DEFAULT_STABILITY),
    )
    await db.commit()
    return ReviewSchedule(
        topic=topic,
        course_id=course_id,
        interval_index=0,
        next_review_at=next_at,
        difficulty=FSRS_DEFAULT_DIFFICULTY,
        stability=FSRS_DEFAULT_STABILITY,
        review_count=0,
    )


def _map_interval_to_index(interval_days: int) -> int:
    """Map an FSRS interval to the nearest REVIEW_INTERVALS index for backward compat."""
    best_idx = 0
    best_dist = abs(interval_days - REVIEW_INTERVALS[0])
    for i, val in enumerate(REVIEW_INTERVALS[1:], 1):
        dist = abs(interval_days - val)
        if dist < best_dist:
            best_dist = dist
            best_idx = i
    return best_idx


async def complete_review(
    db: aiosqlite.Connection,
    topic: str,
    course_id: int,
    score: float,
) -> ReviewSchedule:
    """Record a completed review and compute the next review date.

    Uses FSRS-inspired adaptive algorithm:
    - Adjusts difficulty and stability based on score
    - Computes interval from stability
    - Maps interval back to interval_index for backward display compat
    """
    cursor = await db.execute(
        "SELECT interval_index, difficulty, stability, review_count "
        "FROM review_schedule WHERE topic = ? AND course_id = ?",
        (topic, course_id),
    )
    row = await cursor.fetchone()
    difficulty = row[1] if row and row[1] is not None else FSRS_DEFAULT_DIFFICULTY
    stability = row[2] if row and row[2] is not None else FSRS_DEFAULT_STABILITY
    review_count = row[3] if row and row[3] is not None else 0

    new_difficulty, new_stability, interval_days = compute_fsrs_interval(
        difficulty, stability, score
    )
    new_review_count = review_count + 1
    new_index = _map_interval_to_index(interval_days)

    now = datetime.now(UTC)
    next_at = (now + timedelta(days=interval_days)).isoformat()

    await db.execute(
        "INSERT INTO review_schedule (topic, course_id, interval_index, "
        "last_reviewed_at, next_review_at, score_at_last_review, "
        "difficulty, stability, review_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(topic, course_id) DO UPDATE SET "
        "interval_index = excluded.interval_index, "
        "last_reviewed_at = excluded.last_reviewed_at, "
        "next_review_at = excluded.next_review_at, "
        "score_at_last_review = excluded.score_at_last_review, "
        "difficulty = excluded.difficulty, "
        "stability = excluded.stability, "
        "review_count = excluded.review_count",
        (
            topic,
            course_id,
            new_index,
            now.isoformat(),
            next_at,
            score,
            new_difficulty,
            new_stability,
            new_review_count,
        ),
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
        difficulty=new_difficulty,
        stability=new_stability,
        review_count=new_review_count,
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
            difficulty=row[6] if row[6] is not None else FSRS_DEFAULT_DIFFICULTY,
            stability=row[7] if row[7] is not None else FSRS_DEFAULT_STABILITY,
            review_count=row[8] if row[8] is not None else 0,
        )
        for row in rows
    ]


_SELECT_COLS = (
    "topic, course_id, interval_index, last_reviewed_at, next_review_at, "
    "score_at_last_review, difficulty, stability, review_count"
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
