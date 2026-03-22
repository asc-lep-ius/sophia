"""Athena ↔ Chronos integration service.

Cross-module logic that neither Athena nor Chronos should own alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import aiosqlite

from sophia.domain.models import PlanItem, PlanItemType

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


# --- Unified Recommendation Engine (Phase 3) ---

DEADLINE_BASE_WEIGHT = 1.0
REVIEW_BASE_WEIGHT = 0.6
CONFIDENCE_GAP_WEIGHT = 0.3
REVIEW_OVERDUE_BOOST_PER_DAY = 0.1
CONFIDENCE_GAP_THRESHOLD = 0.5  # predicted < 0.5 (= 2.5/5 raw) is a gap


async def build_plan_items(
    db: aiosqlite.Connection,
    horizon_days: int = 14,
) -> list[PlanItem]:
    """Gather items from Chronos + Athena, score them, return sorted.

    Scoring is for SORTING, not prescribing. The student decides.
    """
    items: list[PlanItem] = []
    items.extend(await _deadline_items(db, horizon_days))
    items.extend(await _review_items(db))
    items.extend(await _confidence_gap_items(db))
    items.sort(key=lambda i: i.score, reverse=True)
    return items


async def _deadline_items(
    db: aiosqlite.Connection,
    horizon_days: int,
) -> list[PlanItem]:
    """Build PlanItems from upcoming deadlines with priority scores."""
    from sophia.services.chronos import compute_priority_score, get_deadlines, get_tracked_time

    deadlines = await get_deadlines(db, horizon_days=horizon_days)
    items = []

    for d in deadlines:
        est_cursor = await db.execute(
            "SELECT predicted_hours FROM effort_estimates "
            "WHERE deadline_id = ? ORDER BY estimated_at DESC LIMIT 1",
            (d.id,),
        )
        est_row = await est_cursor.fetchone()
        est_hours = float(est_row[0]) if est_row else None

        tracked = await get_tracked_time(db, d.id)
        confidence = await get_course_confidence(db, d.course_id)
        conf_mult = confidence_priority_multiplier(confidence)
        ps = compute_priority_score(d, est_hours, tracked, confidence_multiplier=conf_mult)

        est_str = f"{est_hours:.1f}h est" if est_hours else "no estimate"
        conf_str = f"confidence {confidence * 5:.1f}/5" if confidence else "no confidence data"
        detail = f"{est_str}, {tracked:.1f}h tracked — {conf_str}"

        items.append(
            PlanItem(
                item_type=PlanItemType.DEADLINE,
                title=d.name,
                course_name=d.course_name,
                course_id=d.course_id,
                score=ps["score"] * DEADLINE_BASE_WEIGHT,
                components=ps,
                due_at=d.due_at.isoformat(),
                detail=detail,
            )
        )

    return items


async def _review_items(db: aiosqlite.Connection) -> list[PlanItem]:
    """Build PlanItems from due reviews."""
    from sophia.services.athena_review import get_due_reviews

    reviews = await get_due_reviews(db)
    items = []

    now = datetime.now(UTC)
    for r in reviews:
        review_due = datetime.fromisoformat(r.next_review_at)
        overdue_days = max(0, (now - review_due).days)
        review_score = REVIEW_BASE_WEIGHT + (overdue_days * REVIEW_OVERDUE_BOOST_PER_DAY)

        exam_date = await get_exam_for_course(db, r.course_id)
        exam_str = ""
        exam_boost = 1.0
        if exam_date:
            days_to_exam = (exam_date - now).days
            if days_to_exam <= 14:
                exam_boost = 1.5
                review_score *= exam_boost
                exam_str = f" — exam in {days_to_exam}d"

        name_cursor = await db.execute(
            "SELECT DISTINCT course_name FROM deadline_cache WHERE course_id = ? LIMIT 1",
            (r.course_id,),
        )
        name_row = await name_cursor.fetchone()
        course_name = name_row[0] if name_row else f"Course {r.course_id}"

        detail = f"review #{r.review_count + 1}, last score: "
        detail += f"{r.score_at_last_review:.0%}" if r.score_at_last_review else "none"
        detail += exam_str

        items.append(
            PlanItem(
                item_type=PlanItemType.REVIEW,
                title=f"Review: {r.topic}",
                course_name=course_name,
                course_id=r.course_id,
                score=review_score,
                components={
                    "base": REVIEW_BASE_WEIGHT,
                    "overdue_days": float(overdue_days),
                    "exam_boost": exam_boost,
                },
                due_at=r.next_review_at,
                detail=detail,
            )
        )

    return items


async def _confidence_gap_items(db: aiosqlite.Connection) -> list[PlanItem]:
    """Build PlanItems from low-confidence topics across all courses."""
    cursor = await db.execute("SELECT DISTINCT course_id FROM confidence_ratings")
    course_ids = [row[0] for row in await cursor.fetchall()]

    items = []
    now = datetime.now(UTC)

    for course_id in course_ids:
        from sophia.services.athena_confidence import get_confidence_ratings

        ratings = await get_confidence_ratings(db, course_id)
        low_ratings = [r for r in ratings if r.predicted < CONFIDENCE_GAP_THRESHOLD]

        exam_date = await get_exam_for_course(db, course_id)
        exam_boost = 1.0
        exam_str = ""
        if exam_date:
            days_to_exam = (exam_date - now).days
            if days_to_exam <= 14:
                exam_boost = 2.0
                exam_str = f" — exam in {days_to_exam}d"

        name_cursor = await db.execute(
            "SELECT DISTINCT course_name FROM deadline_cache WHERE course_id = ? LIMIT 1",
            (course_id,),
        )
        name_row = await name_cursor.fetchone()
        course_name = name_row[0] if name_row else f"Course {course_id}"

        for rating in low_ratings:
            confidence_deficit = 1 - rating.predicted
            gap_score = CONFIDENCE_GAP_WEIGHT * confidence_deficit * exam_boost
            detail = f"confidence: {rating.predicted * 5:.1f}/5{exam_str}"

            items.append(
                PlanItem(
                    item_type=PlanItemType.CONFIDENCE_GAP,
                    title=f"Low confidence: {rating.topic}",
                    course_name=course_name,
                    course_id=course_id,
                    score=gap_score,
                    components={
                        "base": CONFIDENCE_GAP_WEIGHT,
                        "confidence_deficit": confidence_deficit,
                        "exam_boost": exam_boost,
                    },
                    detail=detail,
                )
            )

    return items
