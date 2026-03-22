"""Athena confidence service — confidence-before-reveal metacognitive workflow."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from sophia.domain.models import ConfidenceRating, DifficultyLevel

if TYPE_CHECKING:
    import aiosqlite

    from sophia.infra.di import AppContainer

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
    app: AppContainer,
    topic: str,
    course_id: int,
    rating: int,
) -> ConfidenceRating:
    """Store a student's predicted confidence for a topic.

    Rating is 1-5, mapped to 0.0-1.0 internally.
    """
    predicted = rating_to_score(rating)
    now = datetime.now(UTC).isoformat()

    await app.db.execute(
        "INSERT INTO confidence_ratings (topic, course_id, predicted, rated_at) "
        "VALUES (?, ?, ?, ?)",
        (topic, course_id, predicted, now),
    )
    await app.db.commit()

    from sophia.services.athena_chronos import log_confidence_prediction

    await log_confidence_prediction(app.db, course_id, topic, predicted)

    log.info("confidence_rated", topic=topic, course_id=course_id, predicted=predicted)
    return ConfidenceRating(topic=topic, course_id=course_id, predicted=predicted, rated_at=now)


async def get_confidence_ratings(
    db: aiosqlite.Connection,
    course_id: int,
) -> list[ConfidenceRating]:
    """Load the most recent confidence ratings per topic for a course."""
    cursor = await db.execute(
        "SELECT topic, course_id, predicted, actual, rated_at "
        "FROM confidence_ratings "
        "WHERE course_id = ? "
        "AND id IN ("
        "  SELECT MAX(id) FROM confidence_ratings "
        "  WHERE course_id = ? GROUP BY topic"
        ") "
        "ORDER BY topic",
        (course_id, course_id),
    )
    rows = await cursor.fetchall()
    return [
        ConfidenceRating(
            topic=row[0],
            course_id=row[1],
            predicted=row[2],
            actual=row[3],
            rated_at=row[4] or "",
        )
        for row in rows
    ]


async def get_blind_spots(
    db: aiosqlite.Connection,
    course_id: int,
) -> list[ConfidenceRating]:
    """Find topics where the student is significantly overconfident."""
    ratings = await get_confidence_ratings(db, course_id)
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
    db: aiosqlite.Connection,
    topic: str,
    course_id: int,
    actual: float,
) -> None:
    """Update the most recent confidence rating with an actual score.

    Called by card review (Phase 4.3) or quiz import (Phase 4.6) when
    objective performance data becomes available.
    """
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE confidence_ratings SET actual = ?, actual_at = ? "
        "WHERE id = ("
        "  SELECT MAX(id) FROM confidence_ratings "
        "  WHERE topic = ? AND course_id = ?"
        ")",
        (actual, now, topic, course_id),
    )
    await db.commit()

    from sophia.services.athena_chronos import log_confidence_actual

    await log_confidence_actual(db, course_id, topic, actual)

    log.info("actual_score_updated", topic=topic, course_id=course_id, actual=actual)
