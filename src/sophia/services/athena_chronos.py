"""Athena ↔ Chronos integration service.

Cross-module logic that neither Athena nor Chronos should own alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import aiosqlite

log = structlog.get_logger()

EXAM_BUFFER_DAYS = 1
COMPRESSION_HORIZON_DAYS = 30


async def get_exam_for_course(
    db: aiosqlite.Connection,
    course_id: int,
) -> datetime | None:
    """Return the nearest future exam date for a course, or None."""
    now = datetime.now(UTC).isoformat()
    cursor = await db.execute(
        "SELECT due_at FROM deadline_cache "
        "WHERE course_id = ? AND deadline_type = 'exam' AND due_at > ? "
        "ORDER BY due_at ASC LIMIT 1",
        (course_id, now),
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return datetime.fromisoformat(row[0])


def cap_review_for_exam(
    computed_next_review: datetime,
    exam_date: datetime,
) -> datetime:
    """If the review would land after the exam, cap it to EXAM_BUFFER_DAYS before.

    Only caps if the exam is within COMPRESSION_HORIZON_DAYS.
    Returns the original date if no capping needed.
    """
    buffer = exam_date - timedelta(days=EXAM_BUFFER_DAYS)
    now = datetime.now(UTC)

    if (exam_date - now).days > COMPRESSION_HORIZON_DAYS:
        return computed_next_review

    if computed_next_review > buffer:
        earliest = now + timedelta(days=1)
        return max(buffer, earliest)

    return computed_next_review


async def compress_reviews_for_exam(
    db: aiosqlite.Connection,
    course_id: int,
    exam_date: datetime,
) -> int:
    """Pull forward all review schedules that would miss the exam.

    Returns the number of schedules compressed.
    """
    buffer = exam_date - timedelta(days=EXAM_BUFFER_DAYS)
    now = datetime.now(UTC)

    if buffer <= now:
        return 0

    cursor = await db.execute(
        "SELECT topic, next_review_at FROM review_schedule "
        "WHERE course_id = ? AND next_review_at > ?",
        (course_id, buffer.isoformat()),
    )
    rows = list(await cursor.fetchall())

    compressed = 0
    for topic, _current_next in rows:
        await db.execute(
            "UPDATE review_schedule SET next_review_at = ? WHERE topic = ? AND course_id = ?",
            (buffer.isoformat(), topic, course_id),
        )
        compressed += 1

    if compressed:
        await db.commit()
        log.info(
            "reviews_compressed",
            course_id=course_id,
            exam_date=exam_date.isoformat(),
            count=compressed,
        )

    return compressed


async def compress_all_courses(db: aiosqlite.Connection) -> dict[int, int]:
    """Run compression for all courses with upcoming exams.

    Call this after `sophia deadlines sync`.
    Returns {course_id: compressed_count}.
    """
    now = datetime.now(UTC).isoformat()
    horizon = (datetime.now(UTC) + timedelta(days=COMPRESSION_HORIZON_DAYS)).isoformat()

    cursor = await db.execute(
        "SELECT DISTINCT course_id, due_at FROM deadline_cache "
        "WHERE deadline_type = 'exam' AND due_at > ? AND due_at < ? "
        "ORDER BY due_at ASC",
        (now, horizon),
    )
    exams = list(await cursor.fetchall())

    results: dict[int, int] = {}
    for course_id, due_at_str in exams:
        exam_date = datetime.fromisoformat(due_at_str)
        count = await compress_reviews_for_exam(db, course_id, exam_date)
        if count > 0:
            results[course_id] = count

    return results


# --- Confidence → Priority ---

CONFIDENCE_BOOST_THRESHOLD = 0.6
CONFIDENCE_BOOST_FACTOR = 1.5


async def log_confidence_prediction(
    db: aiosqlite.Connection,
    course_id: int,
    topic: str,
    confidence_rating: float,
) -> None:
    """Write a confidence prediction to metacognition_log.

    Domain: 'confidence:{course_id}'
    Predicted: confidence score (already 0-1 from rating_to_score).
    """
    domain = f"confidence:{course_id}"
    now = datetime.now(UTC).isoformat()

    await db.execute(
        "INSERT OR REPLACE INTO metacognition_log "
        "(domain, item_id, predicted, predicted_at) VALUES (?, ?, ?, ?)",
        (domain, topic, confidence_rating, now),
    )
    await db.commit()


async def log_confidence_actual(
    db: aiosqlite.Connection,
    course_id: int,
    topic: str,
    actual_score: float,
) -> None:
    """Record an actual exam/test score against a confidence prediction."""
    domain = f"confidence:{course_id}"
    now = datetime.now(UTC).isoformat()

    await db.execute(
        "UPDATE metacognition_log SET actual = ?, actual_at = ? WHERE domain = ? AND item_id = ?",
        (actual_score, now, domain, topic),
    )
    await db.commit()


async def get_course_confidence(
    db: aiosqlite.Connection,
    course_id: int,
) -> float | None:
    """Average normalized confidence (0-1) for a course, or None if no ratings."""
    cursor = await db.execute(
        "SELECT AVG(predicted) FROM confidence_ratings WHERE course_id = ?",
        (course_id,),
    )
    row = await cursor.fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def confidence_priority_multiplier(confidence: float | None) -> float:
    """Compute a priority multiplier based on course confidence.

    Low confidence → higher multiplier (up to CONFIDENCE_BOOST_FACTOR).
    High confidence → multiplier of 1.0 (no boost).
    No data → 1.0 (neutral).
    """
    if confidence is None:
        return 1.0

    if confidence >= CONFIDENCE_BOOST_THRESHOLD:
        return 1.0

    t = confidence / CONFIDENCE_BOOST_THRESHOLD
    return CONFIDENCE_BOOST_FACTOR - t * (CONFIDENCE_BOOST_FACTOR - 1.0)
