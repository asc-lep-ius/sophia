"""Athena ↔ Chronos integration service.

Cross-module logic that neither Athena nor Chronos should own alone.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.infra.engine import affected_rows
from sophia.infra.schema import (
    confidence_ratings,
    deadline_cache,
    effort_estimates,
    lecture_downloads,
    metacognition_log,
    review_schedule,
    topic_lecture_links,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from sophia.domain.models import PlanItem, PlanItemType

log = structlog.get_logger()

EXAM_BUFFER_DAYS = 1
COMPRESSION_HORIZON_DAYS = 30


async def get_exam_for_course(
    session: AsyncSession,
    course_id: int,
) -> datetime | None:
    """Return the nearest future exam date for a course, or None."""
    due_at = await session.scalar(
        select(deadline_cache.c.due_at)
        .where(
            deadline_cache.c.course_id == course_id,
            deadline_cache.c.deadline_type == "exam",
            deadline_cache.c.due_at > datetime.now(UTC).isoformat(),
        )
        .order_by(deadline_cache.c.due_at.asc())
        .limit(1)
    )
    return None if due_at is None else datetime.fromisoformat(due_at)


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
    session: AsyncSession,
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

    result = await session.execute(
        update(review_schedule)
        .where(
            review_schedule.c.course_id == course_id,
            review_schedule.c.next_review_at > buffer,
        )
        .values(next_review_at=buffer)
    )
    compressed = affected_rows(result)

    if compressed:
        log.info(
            "reviews_compressed",
            course_id=course_id,
            exam_date=exam_date.isoformat(),
            count=compressed,
        )

    return compressed


async def compress_all_courses(session: AsyncSession) -> dict[int, int]:
    """Run compression for all courses with upcoming exams.

    Call this after `sophia deadlines sync`.
    Returns {course_id: compressed_count}.
    """
    now = datetime.now(UTC).isoformat()
    horizon = (datetime.now(UTC) + timedelta(days=COMPRESSION_HORIZON_DAYS)).isoformat()

    exams = (
        await session.execute(
            select(deadline_cache.c.course_id, deadline_cache.c.due_at)
            .where(
                deadline_cache.c.deadline_type == "exam",
                deadline_cache.c.due_at > now,
                deadline_cache.c.due_at < horizon,
            )
            .distinct()
            .order_by(deadline_cache.c.due_at.asc())
        )
    ).all()

    results: dict[int, int] = {}
    for course_id, due_at_str in exams:
        exam_date = datetime.fromisoformat(due_at_str)
        count = await compress_reviews_for_exam(session, course_id, exam_date)
        if count > 0:
            results[course_id] = count

    return results


# --- Confidence → Priority ---

CONFIDENCE_BOOST_THRESHOLD = 0.6
CONFIDENCE_BOOST_FACTOR = 1.5


async def log_confidence_prediction(
    session: AsyncSession,
    course_id: int,
    topic: str,
    confidence_rating: float,
) -> None:
    """Write a confidence prediction to metacognition_log.

    Domain: 'confidence:{course_id}'
    Predicted: confidence score (already 0-1 from rating_to_score).

    The row's course_id column is deliberately left at its default: the scope
    lives in the domain string for confidence rows. Any future course filter
    over them must match on domain, not course_id — see
    the 023 tenancy backfill, which backfilled effort rows only.
    """
    domain = f"confidence:{course_id}"
    statement = pg_insert(metacognition_log).values(
        domain=domain,
        item_id=topic,
        predicted=confidence_rating,
        predicted_at=datetime.now(UTC),
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[metacognition_log.c.domain, metacognition_log.c.item_id],
            set_={
                "predicted": statement.excluded.predicted,
                "predicted_at": statement.excluded.predicted_at,
                # A re-rating voids the old outcome; see record_estimate.
                "actual": None,
                "actual_at": None,
            },
        )
    )


async def log_confidence_actual(
    session: AsyncSession,
    course_id: int,
    topic: str,
    actual_score: float,
) -> None:
    """Record an actual exam/test score against a confidence prediction."""
    domain = f"confidence:{course_id}"
    await session.execute(
        update(metacognition_log)
        .where(
            metacognition_log.c.domain == domain,
            metacognition_log.c.item_id == topic,
        )
        .values(actual=actual_score, actual_at=datetime.now(UTC))
    )


async def get_course_confidence(
    session: AsyncSession,
    course_id: int,
) -> float | None:
    """Average normalized confidence (0-1) for a course, or None if no ratings."""
    average = await session.scalar(
        select(func.avg(confidence_ratings.c.predicted)).where(
            confidence_ratings.c.course_id == course_id,
        )
    )
    return None if average is None else float(average)


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
# Higher than CONFIDENCE_GAP_WEIGHT — zero exposure is worse than low confidence
MISSED_TOPIC_BASE_WEIGHT = 0.4
REVIEW_OVERDUE_BOOST_PER_DAY = 0.1
CONFIDENCE_GAP_THRESHOLD = 0.5  # predicted < 0.5 (= 2.5/5 raw) is a gap


async def _course_name(session: AsyncSession, course_id: int) -> str:
    """Best-known display name for a course, falling back to its id."""
    name = await session.scalar(
        select(deadline_cache.c.course_name)
        .where(deadline_cache.c.course_id == course_id)
        .distinct()
        .limit(1)
    )
    return name or f"Course {course_id}"


async def build_plan_items(
    session: AsyncSession,
    horizon_days: int = 14,
) -> list[PlanItem]:
    """Gather items from Chronos + Athena, score them, return sorted.

    Scoring is for SORTING, not prescribing. The student decides.
    """
    items: list[PlanItem] = []
    items.extend(await _deadline_items(session, horizon_days))
    items.extend(await _review_items(session))
    items.extend(await _confidence_gap_items(session))
    items.extend(await _missed_topic_items(session))
    items.sort(key=lambda i: i.score, reverse=True)
    return items


async def _deadline_items(
    session: AsyncSession,
    horizon_days: int,
) -> list[PlanItem]:
    """Build PlanItems from upcoming deadlines with priority scores."""
    from sophia.services.chronos import compute_priority_score, get_deadlines, get_tracked_time

    deadlines = await get_deadlines(session, horizon_days=horizon_days)
    items: list[PlanItem] = []

    for d in deadlines:
        predicted = await session.scalar(
            select(effort_estimates.c.predicted_hours)
            .where(effort_estimates.c.deadline_id == d.id)
            .order_by(effort_estimates.c.estimated_at.desc())
            .limit(1)
        )
        est_hours = float(predicted) if predicted is not None else None

        tracked = await get_tracked_time(session, d.id)
        confidence = await get_course_confidence(session, d.course_id)
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


async def _review_items(session: AsyncSession) -> list[PlanItem]:
    """Build PlanItems from due reviews."""
    from sophia.services.athena_review import get_due_reviews

    reviews = await get_due_reviews(session)
    items: list[PlanItem] = []

    now = datetime.now(UTC)
    for r in reviews:
        review_due = datetime.fromisoformat(r.next_review_at)
        overdue_days = max(0, (now - review_due).days)
        review_score = REVIEW_BASE_WEIGHT + (overdue_days * REVIEW_OVERDUE_BOOST_PER_DAY)

        exam_date = await get_exam_for_course(session, r.course_id)
        exam_str = ""
        exam_boost = 1.0
        if exam_date:
            days_to_exam = (exam_date - now).days
            if days_to_exam <= 14:
                exam_boost = 1.5
                review_score *= exam_boost
                exam_str = f" — exam in {days_to_exam}d"

        course_name = await _course_name(session, r.course_id)

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


async def _confidence_gap_items(session: AsyncSession) -> list[PlanItem]:
    """Build PlanItems from low-confidence topics across all courses."""
    course_ids = list(
        (await session.scalars(select(confidence_ratings.c.course_id).distinct())).all()
    )

    items: list[PlanItem] = []
    now = datetime.now(UTC)

    for course_id in course_ids:
        from sophia.services.athena_confidence import get_confidence_ratings

        ratings = await get_confidence_ratings(session, course_id)
        low_ratings = [r for r in ratings if r.predicted < CONFIDENCE_GAP_THRESHOLD]

        exam_date = await get_exam_for_course(session, course_id)
        exam_boost = 1.0
        exam_str = ""
        if exam_date:
            days_to_exam = (exam_date - now).days
            if days_to_exam <= 14:
                exam_boost = 2.0
                exam_str = f" — exam in {days_to_exam}d"

        course_name = await _course_name(session, course_id)

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


async def _missed_topic_items(session: AsyncSession) -> list[PlanItem]:
    """Build PlanItems from topics only covered in missed lectures.

    Pedagogical rationale: topics the student was never exposed to are the most
    dangerous gaps — no disequilibrium exists because the student doesn't know
    what they don't know. By surfacing these in the planner, we create awareness.
    """
    from sophia.services.hermes_manage import get_catch_up_info

    module_ids = list(
        (
            await session.scalars(
                select(lecture_downloads.c.module_id)
                .where(lecture_downloads.c.missed_at.is_not(None))
                .distinct()
            )
        ).all()
    )
    if not module_ids:
        return []

    items: list[PlanItem] = []
    now = datetime.now(UTC)

    for module_id in module_ids:
        info = await get_catch_up_info(session, module_id)
        if not info.missed_only_topics:
            continue

        missed_episode_ids = [ep.episode_id for ep in info.missed_episodes]
        if not missed_episode_ids:
            continue

        course_ids = list(
            (
                await session.scalars(
                    select(topic_lecture_links.c.course_id)
                    .where(topic_lecture_links.c.episode_id.in_(missed_episode_ids))
                    .distinct()
                )
            ).all()
        )

        for course_id in course_ids:
            exam_date = await get_exam_for_course(session, course_id)
            exam_boost = 1.0
            exam_str = ""
            if exam_date:
                days_to_exam = (exam_date - now).days
                if days_to_exam <= 14:
                    exam_boost = 2.0
                    exam_str = f" — exam in {days_to_exam}d"

            course_name = await _course_name(session, course_id)

            for topic in info.missed_only_topics:
                score = MISSED_TOPIC_BASE_WEIGHT * exam_boost
                detail = f"zero exposure — missed lecture{exam_str}"

                items.append(
                    PlanItem(
                        item_type=PlanItemType.MISSED_TOPIC,
                        title=f"Missed topic: {topic}",
                        course_name=course_name,
                        course_id=course_id,
                        score=score,
                        components={
                            "base": MISSED_TOPIC_BASE_WEIGHT,
                            "exposure_deficit": 1.0,
                            "exam_boost": exam_boost,
                        },
                        detail=detail,
                    )
                )

    return items


async def get_scaffold_hint(
    session: AsyncSession,
    course_id: int,
) -> str | None:
    """Compare Athena scaffold (study maturity) with Chronos scaffold
    (estimation maturity) and return an observational hint.

    Returns None if no meaningful contrast exists.
    """
    from sophia.domain.models import DeadlineType, EstimationScaffold
    from sophia.services.athena_study import get_explanation_count
    from sophia.services.athena_study import get_scaffold_level as athena_scaffold_level
    from sophia.services.chronos import get_scaffold_level as chronos_scaffold_level

    explanation_count = await get_explanation_count(session, course_id)
    athena_level = athena_scaffold_level(explanation_count)

    chronos_level = await chronos_scaffold_level(
        session,
        DeadlineType.EXAM,
        course_id=course_id,
    )

    athena_open = athena_level == 0
    chronos_open = chronos_level == EstimationScaffold.OPEN

    if athena_open and not chronos_open:
        return (
            "You've developed strong study habits for this course, "
            "but your effort estimates still need calibration."
        )
    if not athena_open and chronos_open:
        return (
            "Your time estimates are well-calibrated for this type of work, "
            "but your study practice is still developing."
        )
    return None
