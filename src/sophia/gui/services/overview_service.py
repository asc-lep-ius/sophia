"""Course overview service — aggregated health metrics per course."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

import structlog
from sqlalchemy import case, distinct, func, select

from sophia.infra.schema import (
    confidence_ratings,
    deadline_cache,
    study_sessions,
    topic_mappings,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# Health score thresholds
_THRESHOLD_RED = 5
_THRESHOLD_YELLOW = 2

# Scoring weights
_OVERDUE_WEIGHT = 2
_BLIND_SPOT_MIN = 3
_NEAR_DEADLINE_DAYS = 3
_NEAR_DEADLINE_SCORE = 3
_LOW_HOURS_THRESHOLD = 1.0
_WORKLOAD_IMBALANCE_RATIO = 3.0
_BLIND_SPOT_INSIGHT_MIN = 3
_BLIND_SPOT_ERROR_THRESHOLD = 0.2


@dataclass
class CourseSummary:
    """Aggregated status snapshot for a single course."""

    course_id: int
    course_name: str
    upcoming_count: int
    overdue_count: int
    blind_spot_count: int
    avg_calibration_error: float | None
    hours_this_week: float
    topics_total: int
    topics_rated: int
    days_until_nearest: int | None
    health: Literal["green", "yellow", "red"]


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def compute_course_health(
    overdue_count: int,
    blind_spot_count: int,
    days_until_nearest: int | None,
    hours_tracked_this_week: float,
) -> Literal["green", "yellow", "red"]:
    """Compute health rating from course metrics."""
    score = 0
    if overdue_count > 0:
        score += overdue_count * _OVERDUE_WEIGHT
    if blind_spot_count > _BLIND_SPOT_MIN:
        score += blind_spot_count
    if days_until_nearest is not None and days_until_nearest < _NEAR_DEADLINE_DAYS:
        score += _NEAR_DEADLINE_SCORE
    if hours_tracked_this_week < _LOW_HOURS_THRESHOLD:
        score += 1
    if score >= _THRESHOLD_RED:
        return "red"
    if score >= _THRESHOLD_YELLOW:
        return "yellow"
    return "green"


def health_tooltip(summary: CourseSummary) -> str:
    """Generate tooltip text for the health indicator."""
    parts: list[str] = []
    if summary.overdue_count > 0:
        noun = "deadline" if summary.overdue_count == 1 else "deadlines"
        parts.append(f"{summary.overdue_count} overdue {noun}")
    if summary.blind_spot_count > 0:
        noun = "blind spot" if summary.blind_spot_count == 1 else "blind spots"
        parts.append(f"{summary.blind_spot_count} {noun}")
    if not parts:
        return "On track"
    return ", ".join(parts) + " need attention"


def rank_by_urgency(summaries: list[CourseSummary]) -> list[CourseSummary]:
    """Sort summaries by urgency: red > yellow > green, then by issue count desc."""
    health_order: dict[str, int] = {"red": 0, "yellow": 1, "green": 2}
    return sorted(
        summaries,
        key=lambda s: (health_order[s.health], -(s.overdue_count + s.blind_spot_count)),
    )


def compute_workload_insights(summaries: list[CourseSummary]) -> list[str]:
    """Generate cross-course insight strings."""
    insights: list[str] = []

    # Workload imbalance
    tracked = [(s.course_name, s.hours_this_week) for s in summaries if s.hours_this_week > 0]
    if len(tracked) >= 2:
        tracked.sort(key=lambda x: x[1], reverse=True)
        most, least = tracked[0], tracked[-1]
        if least[1] > 0:
            ratio = most[1] / least[1]
            if ratio >= _WORKLOAD_IMBALANCE_RATIO:
                insights.append(
                    f"{most[0]} is taking {ratio:.0f}x more time than {least[0]}. "
                    "Consider rebalancing."
                )

    # Blind spot concentration
    with_blind = [(s.course_name, s.blind_spot_count) for s in summaries if s.blind_spot_count > 0]
    if with_blind:
        with_blind.sort(key=lambda x: x[1], reverse=True)
        worst_name, worst_count = with_blind[0]
        if worst_count >= _BLIND_SPOT_INSIGHT_MIN:
            insights.append(
                f"{worst_name} has the most calibration gaps ({worst_count}). "
                "Study sessions there will have the highest impact."
            )

    return insights


# ---------------------------------------------------------------------------
# Async data aggregation
# ---------------------------------------------------------------------------


async def get_course_summaries(db: AsyncSession) -> list[CourseSummary]:
    """Aggregate course data from local cache tables. No MoodleAPI calls."""
    now = datetime.now(UTC)
    week_ago = (now - timedelta(days=7)).isoformat()
    now_iso = now.isoformat()

    courses = (
        await db.execute(
            select(deadline_cache.c.course_id, deadline_cache.c.course_name)
            .distinct()
            .order_by(deadline_cache.c.course_name)
        )
    ).all()
    if not courses:
        return []

    summaries: list[CourseSummary] = []
    for course in courses:
        course_id, course_name = course.course_id, course.course_name
        upcoming, overdue = await _fetch_deadline_counts(db, course_id, now_iso)
        days_until_nearest = await _fetch_nearest_deadline(db, course_id, now_iso, now)
        blind_spot_count, avg_cal = await _fetch_calibration_data(db, course_id)
        topics_total, topics_rated = await _fetch_topic_counts(db, course_id)
        hours = await _fetch_weekly_hours(db, course_id, week_ago)

        health = compute_course_health(overdue, blind_spot_count, days_until_nearest, hours)

        summaries.append(
            CourseSummary(
                course_id=course_id,
                course_name=course_name,
                upcoming_count=upcoming,
                overdue_count=overdue,
                blind_spot_count=blind_spot_count,
                avg_calibration_error=avg_cal,
                hours_this_week=round(hours, 1),
                topics_total=topics_total,
                topics_rated=topics_rated,
                days_until_nearest=days_until_nearest,
                health=health,
            )
        )

    return summaries


# ---------------------------------------------------------------------------
# DB query helpers (keep get_course_summaries readable)
# ---------------------------------------------------------------------------


async def _fetch_deadline_counts(db: AsyncSession, course_id: int, now_iso: str) -> tuple[int, int]:
    row = (
        await db.execute(
            select(
                func.sum(case((deadline_cache.c.due_at >= now_iso, 1), else_=0)).label("upcoming"),
                func.sum(case((deadline_cache.c.due_at < now_iso, 1), else_=0)).label("overdue"),
            ).where(deadline_cache.c.course_id == course_id)
        )
    ).one()
    return int(row.upcoming or 0), int(row.overdue or 0)


async def _fetch_nearest_deadline(
    db: AsyncSession,
    course_id: int,
    now_iso: str,
    now: datetime,
) -> int | None:
    nearest = await db.scalar(
        select(func.min(deadline_cache.c.due_at)).where(
            deadline_cache.c.course_id == course_id,
            deadline_cache.c.due_at >= now_iso,
        )
    )
    if not nearest:
        return None
    nearest_dt = datetime.fromisoformat(nearest)
    if nearest_dt.tzinfo is None:
        nearest_dt = nearest_dt.replace(tzinfo=UTC)
    return (nearest_dt - now).days


async def _fetch_calibration_data(db: AsyncSession, course_id: int) -> tuple[int, float | None]:
    ratings = (
        await db.execute(
            select(confidence_ratings.c.predicted, confidence_ratings.c.actual).where(
                confidence_ratings.c.course_id == course_id,
                confidence_ratings.c.actual.is_not(None),
            )
        )
    ).all()
    blind_spot_count = 0
    cal_errors: list[float] = []
    for rating in ratings:
        error = rating.predicted - rating.actual
        cal_errors.append(error)
        if error > _BLIND_SPOT_ERROR_THRESHOLD:
            blind_spot_count += 1
    avg_cal = sum(cal_errors) / len(cal_errors) if cal_errors else None
    return blind_spot_count, avg_cal


async def _fetch_topic_counts(db: AsyncSession, course_id: int) -> tuple[int, int]:
    topics_total = await db.scalar(
        select(func.count())
        .select_from(topic_mappings)
        .where(topic_mappings.c.course_id == course_id)
    )
    topics_rated = await db.scalar(
        select(func.count(distinct(confidence_ratings.c.topic))).where(
            confidence_ratings.c.course_id == course_id,
        )
    )
    return topics_total or 0, topics_rated or 0


async def _fetch_weekly_hours(db: AsyncSession, course_id: int, week_ago: str) -> float:
    sessions = (
        await db.execute(
            select(study_sessions.c.started_at, study_sessions.c.completed_at).where(
                study_sessions.c.course_id == course_id,
                study_sessions.c.started_at >= datetime.fromisoformat(week_ago),
                study_sessions.c.completed_at.is_not(None),
            )
        )
    ).all()
    hours = 0.0
    for row in sessions:
        if row.started_at is None or row.completed_at is None:
            continue
        hours += (row.completed_at - row.started_at).total_seconds() / 3600
    return hours
