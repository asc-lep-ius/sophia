"""Chronos export & past-deadline query helpers.

Extracted from ``chronos.py`` to keep that module under 800 lines.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sophia.domain.models import CalibrationMetrics, Deadline, DeadlineType
from sophia.services.chronos import get_deadlines

if TYPE_CHECKING:
    import aiosqlite


async def export_deadlines_ics(
    db: aiosqlite.Connection,
    horizon_days: int = 30,
) -> str:
    """Export upcoming deadlines as an ICS calendar string."""
    from icalendar import Calendar, Event  # type: ignore[import-untyped]

    deadlines = await get_deadlines(db, horizon_days=horizon_days)

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


async def get_missed_deadlines(
    db: aiosqlite.Connection,
    *,
    course_id: int | None = None,
    limit: int = 50,
) -> list[Deadline]:
    """Return past-due deadlines, most recent first."""
    now = datetime.now(UTC).isoformat()
    query = (
        "SELECT id, name, course_id, course_name, deadline_type, due_at, "
        "grade_weight, submission_status, url, extra "
        "FROM deadline_cache "
        "WHERE due_at < ? "
    )
    params: list[str | int] = [now]
    if course_id is not None:
        query += "AND course_id = ? "
        params.append(course_id)
    query += "ORDER BY due_at DESC LIMIT ?"
    params.append(limit)

    cursor = await db.execute(query, params)
    return [
        Deadline(
            id=row[0],
            name=row[1],
            course_id=row[2],
            course_name=row[3],
            deadline_type=DeadlineType(row[4]),
            due_at=datetime.fromisoformat(row[5]),
            grade_weight=row[6],
            submission_status=row[7],
            url=row[8],
            extra=json.loads(row[9]) if row[9] else {},
        )
        for row in await cursor.fetchall()
    ]


async def get_upcoming_exams(
    db: aiosqlite.Connection,
    course_id: int | None = None,
) -> list[Deadline]:
    """Return exam deadlines from cache. Athena integration point."""
    now = datetime.now(UTC).isoformat()
    query = (
        "SELECT id, name, course_id, course_name, deadline_type, due_at, "
        "grade_weight, submission_status, url, extra "
        "FROM deadline_cache "
        "WHERE deadline_type = 'exam' AND due_at > ? "
    )
    params: list[str | int] = [now]
    if course_id is not None:
        query += "AND course_id = ? "
        params.append(course_id)
    query += "ORDER BY due_at ASC"

    cursor = await db.execute(query, params)
    return [
        Deadline(
            id=row[0],
            name=row[1],
            course_id=row[2],
            course_name=row[3],
            deadline_type=DeadlineType(row[4]),
            due_at=datetime.fromisoformat(row[5]),
            grade_weight=row[6],
            submission_status=row[7],
            url=row[8],
            extra=json.loads(row[9]) if row[9] else {},
        )
        for row in await cursor.fetchall()
    ]


# ---------------------------------------------------------------------------
# Calibration metrics
# ---------------------------------------------------------------------------

_MIN_CALIBRATION_SAMPLES = 3
_TREND_WINDOW = 5
_TREND_THRESHOLD = 0.10


async def get_calibration_metrics(
    db: aiosqlite.Connection,
    deadline_type: DeadlineType | None = None,
) -> list[CalibrationMetrics]:
    """Per-domain estimation accuracy: bias, MAE, trend."""
    query = (
        "SELECT domain, predicted, actual, predicted_at "
        "FROM metacognition_log "
        "WHERE domain LIKE 'effort:%' AND actual IS NOT NULL "
    )
    params: list[str | int] = []
    if deadline_type is not None:
        query += "AND domain = ? "
        params.append(f"effort:{deadline_type.value}")
    query += "ORDER BY predicted_at ASC"

    cursor = await db.execute(query, params)
    rows = list(await cursor.fetchall())
    grouped: dict[str, list[tuple[float, float]]] = {}
    for domain, predicted, actual, _ts in rows:
        grouped.setdefault(domain, []).append((float(predicted), float(actual)))

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
