"""Chronos export & past-deadline query helpers.

Extracted from ``chronos.py`` to keep that module under 800 lines.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from sophia.domain.models import CalibrationMetrics, Deadline, DeadlineType
from sophia.infra.schema import deadline_cache, metacognition_log

if TYPE_CHECKING:
    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncSession


async def export_deadlines_ics(
    session: AsyncSession,
    *,
    course_id: int | None = None,
    horizon_days: int = 30,
) -> str:
    """Export upcoming deadlines as an ICS calendar string."""
    from icalendar import Calendar, Event  # type: ignore[import-untyped]

    # Imported here because chronos re-exports this module for the CLI, and a
    # module-level import would make that cycle depend on import order.
    from sophia.services.chronos import get_deadlines

    deadlines = await get_deadlines(session, course_id=course_id, horizon_days=horizon_days)

    cal = Calendar()
    cal.add("prodid", "-//Sophia//Chronos//EN")  # type: ignore[reportUnknownMemberType]
    cal.add("version", "2.0")  # type: ignore[reportUnknownMemberType]

    for d in deadlines:
        event = Event()
        event.add("summary", d.name)  # type: ignore[reportUnknownMemberType]
        event.add("dtstart", d.due_at)  # type: ignore[reportUnknownMemberType]
        event.add("dtend", d.due_at)  # type: ignore[reportUnknownMemberType]
        event.add("uid", d.id)  # type: ignore[reportUnknownMemberType]
        desc = f"{d.course_name} | {d.deadline_type.value}"
        event.add("description", desc)  # type: ignore[reportUnknownMemberType]
        cal.add_component(event)

    return cal.to_ical().decode()


def _row_to_deadline(row: Row[tuple[object, ...]]) -> Deadline:
    return Deadline(
        id=row.id,
        name=row.name,
        course_id=row.course_id,
        course_name=row.course_name,
        deadline_type=DeadlineType(row.deadline_type),
        due_at=datetime.fromisoformat(row.due_at),
        grade_weight=row.grade_weight,
        submission_status=row.submission_status,
        url=row.url,
        extra=json.loads(row.extra) if row.extra else {},
    )


async def get_missed_deadlines(
    session: AsyncSession,
    *,
    course_id: int | None = None,
    limit: int = 50,
) -> list[Deadline]:
    """Return past-due deadlines, most recent first."""
    query = (
        select(deadline_cache)
        .where(deadline_cache.c.due_at < datetime.now(UTC).isoformat())
        .order_by(deadline_cache.c.due_at.desc())
        .limit(limit)
    )
    if course_id is not None:
        query = query.where(deadline_cache.c.course_id == course_id)
    return [_row_to_deadline(row) for row in (await session.execute(query)).all()]


async def get_upcoming_exams(
    session: AsyncSession,
    *,
    course_id: int | None = None,
    horizon_days: int = 30,
) -> list[Deadline]:
    """Return exam deadlines from cache. Athena integration point."""
    now = datetime.now(UTC)
    query = (
        select(deadline_cache)
        .where(
            deadline_cache.c.deadline_type == "exam",
            deadline_cache.c.due_at > now.isoformat(),
            deadline_cache.c.due_at < (now + timedelta(days=horizon_days)).isoformat(),
        )
        .order_by(deadline_cache.c.due_at.asc())
    )
    if course_id is not None:
        query = query.where(deadline_cache.c.course_id == course_id)
    return [_row_to_deadline(row) for row in (await session.execute(query)).all()]


# ---------------------------------------------------------------------------
# Calibration metrics
# ---------------------------------------------------------------------------

_MIN_CALIBRATION_SAMPLES = 3
_TREND_WINDOW = 5
_TREND_THRESHOLD = 0.10


async def get_calibration_metrics(
    session: AsyncSession,
    deadline_type: DeadlineType | None = None,
    *,
    course_id: int | None = None,
) -> list[CalibrationMetrics]:
    """Per-domain estimation accuracy: bias, MAE, trend."""
    query = (
        select(metacognition_log)
        .where(
            metacognition_log.c.domain.like("effort:%"),
            metacognition_log.c.actual.is_not(None),
        )
        .order_by(metacognition_log.c.predicted_at.asc())
    )
    if deadline_type is not None:
        query = query.where(metacognition_log.c.domain == f"effort:{deadline_type.value}")
    if course_id is not None:
        query = query.where(metacognition_log.c.course_id == str(course_id))

    rows = (await session.execute(query)).all()
    grouped: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        grouped.setdefault(row.domain, []).append((float(row.predicted), float(row.actual)))

    results: list[CalibrationMetrics] = []
    for domain, entries in grouped.items():
        if len(entries) < _MIN_CALIBRATION_SAMPLES:
            continue
        errors = [actual - predicted for predicted, actual in entries]
        abs_errors = [abs(e) for e in errors]
        mean_error = sum(errors) / len(errors)
        mae = sum(abs_errors) / len(abs_errors)

        if len(abs_errors) >= _TREND_WINDOW * 2:
            older = abs_errors[-_TREND_WINDOW * 2 : -_TREND_WINDOW]
            recent = abs_errors[-_TREND_WINDOW:]
        else:
            older = abs_errors[: len(abs_errors) // 2]
            recent = abs_errors[len(abs_errors) // 2 :]

        older_mae = sum(older) / len(older) if older else mae
        recent_mae = sum(recent) / len(recent) if recent else mae

        if older_mae > 0 and (older_mae - recent_mae) / older_mae > _TREND_THRESHOLD:
            trend = "improving"
        elif older_mae > 0 and (recent_mae - older_mae) / older_mae > _TREND_THRESHOLD:
            trend = "declining"
        else:
            trend = "stable"

        results.append(
            CalibrationMetrics(
                domain=domain,
                sample_count=len(entries),
                mean_error=mean_error,
                mean_absolute_error=mae,
                trend=trend,
            )
        )
    return results
