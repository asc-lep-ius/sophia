"""API-safe Chronos history and effort aggregation operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from sophia.domain.models import Deadline  # noqa: TC001
from sophia.infra.schema import deadline_reflections, time_entries
from sophia.services.chronos import get_deadlines, get_tracked_time, latest_estimate
from sophia.services.chronos_export import get_missed_deadlines

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

DbRow = tuple[object, ...]


@dataclass(frozen=True, slots=True)
class TimeEntry:
    hours: float
    source: str
    note: str | None
    recorded_at: str


@dataclass(frozen=True, slots=True)
class DeadlineReflection:
    predicted_hours: float | None
    actual_hours: float
    reflection_text: str | None
    reflected_at: str


@dataclass(frozen=True, slots=True)
class DayEffort:
    date: str
    deadline_efforts: dict[str, float]
    unestimated: list[str]
    total: float


async def get_past_deadlines(
    session: AsyncSession,
    *,
    course_id: int | None = None,
    limit: int = 50,
) -> list[Deadline]:
    """Fetch past deadlines without GUI exception fallbacks."""
    return await get_missed_deadlines(session, course_id=course_id, limit=limit)


async def get_time_entries(
    session: AsyncSession,
    deadline_id: str,
) -> list[TimeEntry]:
    """Fetch time entries for a deadline, ordered by recorded timestamp."""
    rows = (
        await session.execute(
            select(time_entries)
            .where(time_entries.c.deadline_id == deadline_id)
            .order_by(time_entries.c.recorded_at)
        )
    ).all()
    return [
        TimeEntry(
            hours=_float_cell(row.hours),
            source=str(row.source),
            note=str(row.note) if row.note is not None else None,
            recorded_at=str(row.recorded_at),
        )
        for row in rows
    ]


async def get_deadline_reflection(
    session: AsyncSession,
    deadline_id: str,
) -> DeadlineReflection | None:
    """Fetch the most recent reflection for a deadline."""
    row = (
        await session.execute(
            select(deadline_reflections)
            .where(deadline_reflections.c.deadline_id == deadline_id)
            .order_by(deadline_reflections.c.id.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        return None
    return DeadlineReflection(
        predicted_hours=(
            _float_cell(row.predicted_hours) if row.predicted_hours is not None else None
        ),
        actual_hours=_float_cell(row.actual_hours),
        reflection_text=str(row.reflection_text) if row.reflection_text is not None else None,
        reflected_at=str(row.reflected_at),
    )


async def get_effort_distribution(
    session: AsyncSession,
    *,
    course_id: int | None = None,
    horizon_days: int = 14,
) -> list[DayEffort]:
    """Fetch deadlines, latest estimates, and tracked time for effort distribution."""
    deadlines = await get_deadlines(session, course_id=course_id, horizon_days=horizon_days)
    estimates: dict[str, float] = {}
    tracked: dict[str, float] = {}

    for deadline in deadlines:
        estimate = await latest_estimate(session, deadline.id)
        if estimate is not None:
            estimates[deadline.id] = estimate
        tracked[deadline.id] = await get_tracked_time(session, deadline.id)

    return compute_effort_distribution(
        deadlines=deadlines,
        estimates=estimates,
        tracked=tracked,
        today=datetime.now(UTC).strftime("%Y-%m-%d"),
        horizon_days=horizon_days,
    )


def compute_effort_distribution(
    *,
    deadlines: list[Deadline],
    estimates: dict[str, float],
    tracked: dict[str, float],
    today: str,
    horizon_days: int = 14,
) -> list[DayEffort]:
    """Distribute remaining estimated effort evenly across available days."""
    today_date = date.fromisoformat(today)
    horizon_end = today_date + timedelta(days=horizon_days)
    day_efforts: dict[str, dict[str, float]] = {}
    day_unestimated: dict[str, list[str]] = {}

    for deadline in deadlines:
        due_date = deadline.due_at.date()
        if due_date < today_date:
            continue

        estimate = estimates.get(deadline.id)
        if estimate is None:
            _mark_unestimated_deadline(
                day_efforts,
                day_unestimated,
                deadline,
                today_date,
                horizon_end,
            )
            continue

        remaining = max(estimate - tracked.get(deadline.id, 0.0), 0.0)
        if remaining <= 0.0:
            continue

        spread_days = _spread_days(today_date, deadline.due_at.date(), horizon_end)
        if not spread_days:
            continue

        per_day = remaining / len(spread_days)
        for day in spread_days:
            day_efforts.setdefault(day, {})[deadline.name] = round(per_day, 2)

    return [
        DayEffort(
            date=day,
            deadline_efforts=day_efforts.get(day, {}),
            unestimated=day_unestimated.get(day, []),
            total=round(sum(day_efforts.get(day, {}).values()), 2),
        )
        for day in sorted(set(day_efforts) | set(day_unestimated))
    ]


def _mark_unestimated_deadline(
    day_efforts: dict[str, dict[str, float]],
    day_unestimated: dict[str, list[str]],
    deadline: Deadline,
    today_date: date,
    horizon_end: date,
) -> None:
    for day in _spread_days(today_date, deadline.due_at.date(), horizon_end):
        day_unestimated.setdefault(day, []).append(deadline.name)
        day_efforts.setdefault(day, {})


def _spread_days(today_date: date, due_date: date, horizon_end: date) -> list[str]:
    spread_end = min(due_date, horizon_end - timedelta(days=1))
    days: list[str] = []
    cursor = today_date
    while cursor <= spread_end:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return days


def _float_cell(value: object) -> float:
    if isinstance(value, int | float | str):
        return float(value)
    msg = "database value must be convertible to float"
    raise TypeError(msg)
