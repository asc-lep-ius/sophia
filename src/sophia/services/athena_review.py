"""Athena spaced review scheduling service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.domain.models import REVIEW_INTERVALS, ReviewSchedule
from sophia.infra.schema import review_schedule

if TYPE_CHECKING:
    from sqlalchemy import Row, Select
    from sqlalchemy.ext.asyncio import AsyncSession

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
    session: AsyncSession,
    topic: str,
    course_id: int,
) -> ReviewSchedule:
    """Create or reset a review schedule for a topic.

    Sets next_review_at to now + first interval (1 day).
    Initializes FSRS columns with defaults.
    """
    now = datetime.now(UTC)
    next_at = now + timedelta(days=REVIEW_INTERVALS[0])
    statement = pg_insert(review_schedule).values(
        topic=topic,
        course_id=course_id,
        interval_index=0,
        next_review_at=next_at,
        difficulty=FSRS_DEFAULT_DIFFICULTY,
        stability=FSRS_DEFAULT_STABILITY,
        review_count=0,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[review_schedule.c.topic, review_schedule.c.course_id],
            set_={
                "interval_index": 0,
                "next_review_at": statement.excluded.next_review_at,
                "last_reviewed_at": None,
                "score_at_last_review": None,
                "difficulty": statement.excluded.difficulty,
                "stability": statement.excluded.stability,
                "review_count": 0,
            },
        )
    )
    return ReviewSchedule(
        topic=topic,
        course_id=course_id,
        interval_index=0,
        next_review_at=next_at.isoformat(),
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
    session: AsyncSession,
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
    row = (
        await session.execute(
            select(
                review_schedule.c.interval_index,
                review_schedule.c.difficulty,
                review_schedule.c.stability,
                review_schedule.c.review_count,
            ).where(
                review_schedule.c.topic == topic,
                review_schedule.c.course_id == course_id,
            )
        )
    ).one_or_none()
    difficulty = row.difficulty if row and row.difficulty is not None else FSRS_DEFAULT_DIFFICULTY
    stability = row.stability if row and row.stability is not None else FSRS_DEFAULT_STABILITY
    review_count = row.review_count if row and row.review_count is not None else 0

    new_difficulty, new_stability, interval_days = compute_fsrs_interval(
        difficulty, stability, score
    )

    # Exam-aware review compression (Chronos integration)
    from sophia.services.athena_chronos import cap_review_for_exam, get_exam_for_course

    now = datetime.now(UTC)
    computed_next = now + timedelta(days=interval_days)
    exam_date = await get_exam_for_course(session, course_id)
    if exam_date is not None:
        capped = cap_review_for_exam(computed_next, exam_date)
        if capped != computed_next:
            interval_days = max(1, (capped - now).days)
            log.info(
                "review_capped_for_exam",
                topic=topic,
                original_days=max(1, round(new_stability)),
                capped_days=interval_days,
                exam_date=exam_date.isoformat(),
            )

    new_review_count = review_count + 1
    new_index = _map_interval_to_index(interval_days)

    next_at = now + timedelta(days=interval_days)

    statement = pg_insert(review_schedule).values(
        topic=topic,
        course_id=course_id,
        interval_index=new_index,
        last_reviewed_at=now,
        next_review_at=next_at,
        score_at_last_review=score,
        difficulty=new_difficulty,
        stability=new_stability,
        review_count=new_review_count,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[review_schedule.c.topic, review_schedule.c.course_id],
            set_={
                column: statement.excluded[column]
                for column in (
                    "interval_index",
                    "last_reviewed_at",
                    "next_review_at",
                    "score_at_last_review",
                    "difficulty",
                    "stability",
                    "review_count",
                )
            },
        )
    )

    log.info("review_completed", topic=topic, score=score, next_interval=interval_days)
    return ReviewSchedule(
        topic=topic,
        course_id=course_id,
        interval_index=new_index,
        last_reviewed_at=now.isoformat(),
        next_review_at=next_at.isoformat(),
        score_at_last_review=score,
        difficulty=new_difficulty,
        stability=new_stability,
        review_count=new_review_count,
    )


def _row_to_schedule(row: Row[tuple[object, ...]]) -> ReviewSchedule:
    return ReviewSchedule(
        topic=row.topic,
        course_id=row.course_id,
        interval_index=row.interval_index,
        last_reviewed_at=row.last_reviewed_at.isoformat() if row.last_reviewed_at else None,
        next_review_at=row.next_review_at.isoformat(),
        score_at_last_review=row.score_at_last_review,
        difficulty=row.difficulty if row.difficulty is not None else FSRS_DEFAULT_DIFFICULTY,
        stability=row.stability if row.stability is not None else FSRS_DEFAULT_STABILITY,
        review_count=row.review_count if row.review_count is not None else 0,
    )


def _schedule_query(course_id: int | None) -> Select[tuple[object, ...]]:
    query = select(review_schedule).order_by(review_schedule.c.next_review_at.asc())
    if course_id is not None:
        query = query.where(review_schedule.c.course_id == course_id)
    return query


async def get_due_reviews(
    session: AsyncSession,
    course_id: int | None = None,
) -> list[ReviewSchedule]:
    """Get all topics that are due for review (next_review_at <= now).

    Optionally filter by course_id. Returns oldest-due first.
    """
    query = _schedule_query(course_id).where(
        review_schedule.c.next_review_at <= datetime.now(UTC),
    )
    return [_row_to_schedule(row) for row in (await session.execute(query)).all()]


async def get_upcoming_reviews(
    session: AsyncSession,
    course_id: int | None = None,
    days_ahead: int = 3,
) -> list[ReviewSchedule]:
    """Get topics due within the next N days (but not yet due). Soonest first."""
    now = datetime.now(UTC)
    query = _schedule_query(course_id).where(
        review_schedule.c.next_review_at > now,
        review_schedule.c.next_review_at <= now + timedelta(days=days_ahead),
    )
    return [_row_to_schedule(row) for row in (await session.execute(query)).all()]


async def get_all_schedules(
    session: AsyncSession,
    course_id: int,
) -> list[ReviewSchedule]:
    """Get all review schedules for a course."""
    query = _schedule_query(course_id)
    return [_row_to_schedule(row) for row in (await session.execute(query)).all()]
