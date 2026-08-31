"""Athena confidence service — confidence-before-reveal metacognitive workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, insert, select, update

from sophia.domain.models import ConfidenceRating, DifficultyLevel
from sophia.infra.schema import confidence_ratings

if TYPE_CHECKING:
    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncSession


log = structlog.get_logger()

CONFIDENCE_SCALE_MIN = 1
CONFIDENCE_SCALE_MAX = 5


def get_topic_difficulty_level(confidence_score: float | None) -> DifficultyLevel:
    """Map a confidence score (0.0-1.0) to a question difficulty level."""
    if confidence_score is None:
        return DifficultyLevel.EXPLAIN
    if confidence_score < 0.4:
        return DifficultyLevel.CUED
    if confidence_score > 0.7:
        return DifficultyLevel.TRANSFER
    return DifficultyLevel.EXPLAIN


def rating_to_score(rating: int) -> float:
    """Convert a 1-5 confidence rating to 0.0-1.0 score."""
    clamped = max(CONFIDENCE_SCALE_MIN, min(CONFIDENCE_SCALE_MAX, rating))
    return (clamped - CONFIDENCE_SCALE_MIN) / (CONFIDENCE_SCALE_MAX - CONFIDENCE_SCALE_MIN)


async def rate_confidence(
    session: AsyncSession,
    topic: str,
    course_id: int,
    rating: int,
) -> ConfidenceRating:
    """Store a student's predicted confidence for a topic.

    Rating is 1-5, mapped to 0.0-1.0 internally.
    """
    predicted = rating_to_score(rating)
    now = datetime.now(UTC)

    await session.execute(
        insert(confidence_ratings).values(
            topic=topic,
            course_id=course_id,
            predicted=predicted,
            rated_at=now,
        )
    )

    from sophia.services.athena_chronos import log_confidence_prediction

    await log_confidence_prediction(session, course_id, topic, predicted)

    log.info("confidence_rated", topic=topic, course_id=course_id, predicted=predicted)
    return ConfidenceRating(
        topic=topic,
        course_id=course_id,
        predicted=predicted,
        rated_at=now.isoformat(),
    )


async def get_confidence_ratings(
    session: AsyncSession,
    course_id: int,
) -> list[ConfidenceRating]:
    """Load the most recent confidence ratings per topic for a course."""
    latest_per_topic = (
        select(func.max(confidence_ratings.c.id))
        .where(confidence_ratings.c.course_id == course_id)
        .group_by(confidence_ratings.c.topic)
        .scalar_subquery()
    )
    rows = (
        await session.execute(
            select(confidence_ratings)
            .where(
                confidence_ratings.c.course_id == course_id,
                confidence_ratings.c.id.in_(latest_per_topic),
            )
            .order_by(confidence_ratings.c.topic)
        )
    ).all()
    return [_row_to_rating(row) for row in rows]


def _row_to_rating(row: Row[tuple[object, ...]]) -> ConfidenceRating:
    return ConfidenceRating(
        topic=row.topic,
        course_id=row.course_id,
        predicted=row.predicted,
        actual=row.actual,
        rated_at=row.rated_at.isoformat() if row.rated_at else "",
    )


async def get_blind_spots(
    session: AsyncSession,
    course_id: int,
) -> list[ConfidenceRating]:
    """Find topics where the student is significantly overconfident."""
    ratings = await get_confidence_ratings(session, course_id)
    return [r for r in ratings if r.is_blind_spot]


def format_calibration_feedback(rating: ConfidenceRating) -> str:
    """Generate growth-oriented feedback text for a confidence rating.

    Per psychologist review: normalize large deltas with empathetic framing.
    """
    err = rating.calibration_error
    if err is None:
        return f"📊 {rating.topic}: predicted {rating.predicted:.0%} — actual score pending"

    abs_err = abs(err)
    actual = rating.actual or 0.0

    if abs_err <= 0.1:
        return (
            f"✅ {rating.topic}: well calibrated "
            f"({rating.predicted:.0%} predicted, {actual:.0%} actual)"
        )

    if err > 0.3:
        return (
            f"🔍 {rating.topic}: predicted {rating.predicted:.0%}, actual {actual:.0%}\n"
            f"   This is a common pattern — most students overestimate {rating.topic} "
            f"before actively studying it. This gap is your biggest learning opportunity."
        )
    if err > 0.1:
        return (
            f"📈 {rating.topic}: predicted {rating.predicted:.0%}, actual {actual:.0%}\n"
            f"   Slightly overconfident — targeted review will close this gap."
        )
    if err < -0.3:
        return (
            f"💪 {rating.topic}: predicted {rating.predicted:.0%}, actual {actual:.0%}\n"
            f"   You know more than you think! This is called 'imposter syndrome' bias."
        )

    return (
        f"📉 {rating.topic}: predicted {rating.predicted:.0%}, actual {actual:.0%}\n"
        f"   Slightly underconfident — you're better at this than you thought."
    )


async def update_actual_score(
    session: AsyncSession,
    topic: str,
    course_id: int,
    actual: float,
) -> None:
    """Update the most recent confidence rating with an actual score.

    Called by card review (Phase 4.3) or quiz import (Phase 4.6) when
    objective performance data becomes available.
    """
    latest = (
        select(func.max(confidence_ratings.c.id))
        .where(
            confidence_ratings.c.topic == topic,
            confidence_ratings.c.course_id == course_id,
        )
        .scalar_subquery()
    )
    await session.execute(
        update(confidence_ratings)
        .where(confidence_ratings.c.id == latest)
        .values(actual=actual, actual_at=datetime.now(UTC))
    )

    from sophia.services.athena_chronos import log_confidence_actual

    await log_confidence_actual(session, course_id, topic, actual)

    log.info("actual_score_updated", topic=topic, course_id=course_id, actual=actual)
