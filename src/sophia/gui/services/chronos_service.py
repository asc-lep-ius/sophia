"""GUI-safe wrappers for Chronos deadline-coach data fetching."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from sophia.domain.errors import AuthError
from sophia.services.chronos import (
    complete_deadline as _complete_deadline,
)
from sophia.services.chronos import (
    compute_priority_score as _compute_priority_score,
)
from sophia.services.chronos import (
    export_deadlines_ics as _export_deadlines_ics,
)
from sophia.services.chronos import (
    format_estimation_feedback as _format_estimation_feedback,
)
from sophia.services.chronos import (
    get_calibration_metrics as _get_calibration_metrics,
)
from sophia.services.chronos import (
    get_deadlines as _get_deadlines,
)
from sophia.services.chronos import (
    get_missed_deadlines as _get_missed_deadlines,
)
from sophia.services.chronos import (
    get_scaffold_level as _get_scaffold_level,
)
from sophia.services.chronos import (
    get_tracked_time as _get_tracked_time,
)
from sophia.services.chronos import (
    record_estimate as _record_estimate,
)
from sophia.services.chronos import (
    record_reflection as _record_reflection,
)
from sophia.services.chronos import (
    record_time as _record_time,
)
from sophia.services.chronos import (
    start_timer as _start_timer,
)
from sophia.services.chronos import (
    stop_timer as _stop_timer,
)
from sophia.services.chronos import (
    sync_deadlines as _sync_deadlines,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from sophia.domain.models import (
        CalibrationMetrics,
        Deadline,
        DeadlineType,
        EffortEstimate,
        EstimationScaffold,
    )
    from sophia.infra.di import AppContainer

    ProgressCallback = Callable[[float, str], Coroutine[Any, Any, None]]

log = structlog.get_logger()


@dataclass
class SyncResult:
    """Structured result from deadline sync — carries status, counts, and errors."""

    status: str  # "success" | "auth_expired" | "network_error" | "error"
    deadline_count: int = 0
    course_count: int = 0
    deadlines: list[Deadline] = field(default_factory=lambda: [])
    error_message: str | None = None


async def get_upcoming_deadlines(
    app: AppContainer,
    *,
    course_id: int | None = None,
    horizon_days: int = 14,
) -> list[Deadline]:
    """Fetch upcoming deadlines within the horizon window."""
    try:
        return await _get_deadlines(app.db, course_id=course_id, horizon_days=horizon_days)
    except Exception:
        log.exception("get_deadlines_failed", course_id=course_id)
        return []


async def get_deadline_priority(
    deadline: Deadline,
    app: AppContainer,
) -> dict[str, float]:
    """Compute priority score for a deadline (sync scorer + async tracked time)."""
    try:
        tracked = await _get_tracked_time(app.db, deadline.id)
        return _compute_priority_score(deadline, None, tracked)
    except Exception:
        log.exception("get_deadline_priority_failed", deadline_id=deadline.id)
        return {}


async def estimate_effort(
    app: AppContainer,
    *,
    deadline_id: str,
    course_id: int,
    predicted_hours: float,
    breakdown: dict[str, float] | None = None,
    intention: str | None = None,
) -> EffortEstimate | None:
    """Record an effort estimate. Passes ``app`` directly (not ``app.db``)."""
    try:
        return await _record_estimate(
            app,
            deadline_id=deadline_id,
            course_id=course_id,
            predicted_hours=predicted_hours,
            breakdown=breakdown,
            intention=intention,
        )
    except Exception:
        log.exception("estimate_effort_failed", deadline_id=deadline_id)
        return None


async def start_deadline_timer(app: AppContainer, deadline_id: str) -> None:
    """Start a timer for a deadline."""
    try:
        await _start_timer(app.db, deadline_id)
    except Exception:
        log.exception("start_timer_failed", deadline_id=deadline_id)


async def stop_deadline_timer(app: AppContainer, deadline_id: str) -> float:
    """Stop a running timer, returning elapsed hours."""
    try:
        return await _stop_timer(app.db, deadline_id)
    except Exception:
        log.exception("stop_timer_failed", deadline_id=deadline_id)
        return 0.0


async def get_deadline_tracked_time(app: AppContainer, deadline_id: str) -> float:
    """Get total tracked time for a deadline."""
    try:
        return await _get_tracked_time(app.db, deadline_id)
    except Exception:
        log.exception("get_tracked_time_failed", deadline_id=deadline_id)
        return 0.0


async def reflect_on_deadline(
    app: AppContainer,
    deadline_id: str,
    *,
    predicted_hours: float | None,
    actual_hours: float,
    reflection_text: str,
) -> None:
    """Record a post-deadline reflection."""
    try:
        await _record_reflection(
            app.db,
            deadline_id,
            predicted_hours=predicted_hours,
            actual_hours=actual_hours,
            reflection_text=reflection_text,
        )
    except Exception:
        log.exception("reflect_on_deadline_failed", deadline_id=deadline_id)


async def get_deadline_scaffold(
    app: AppContainer,
    deadline_type: DeadlineType,
    *,
    course_id: int | None = None,
) -> EstimationScaffold:
    """Get the estimation scaffold level for a deadline type."""
    from sophia.domain.models import EstimationScaffold

    try:
        return await _get_scaffold_level(app.db, deadline_type, course_id=course_id)
    except Exception:
        log.exception("get_scaffold_failed", deadline_type=deadline_type)
        return EstimationScaffold.FULL


def format_deadline_feedback(predicted: float | None, actual: float) -> str:
    """Format estimation feedback (sync)."""
    return _format_estimation_feedback(predicted, actual)


async def get_deadline_calibration(
    app: AppContainer,
    deadline_type: DeadlineType | None = None,
) -> list[CalibrationMetrics]:
    """Get calibration metrics for effort estimation."""
    try:
        return await _get_calibration_metrics(app.db, deadline_type)
    except Exception:
        log.exception("get_calibration_failed", deadline_type=deadline_type)
        return []


async def mark_deadline_complete(
    app: AppContainer,
    deadline_id: str,
) -> tuple[float | None, float, str]:
    """Mark a deadline as complete and return (predicted, actual, feedback)."""
    try:
        return await _complete_deadline(app, deadline_id)
    except Exception:
        log.exception("mark_deadline_complete_failed", deadline_id=deadline_id)
        return None, 0.0, ""


async def sync_deadlines_from_gui(
    app: AppContainer,
    *,
    progress_callback: ProgressCallback | None = None,
) -> SyncResult:
    """Fetch deadlines from all sources and update cache.

    Returns a structured *SyncResult* with status, counts, and errors.
    Accepts an optional async *progress_callback(fraction, message)* for UI feedback.
    """
    try:
        if progress_callback:
            await progress_callback(-1.0, "Syncing courses…")
        deadlines = await _sync_deadlines(app)
        if progress_callback:
            await progress_callback(1.0, f"Synced {len(deadlines)} deadlines")
        return SyncResult(
            status="success",
            deadline_count=len(deadlines),
            deadlines=deadlines,
        )
    except AuthError as exc:
        log.warning("sync_deadlines_auth_expired")
        return SyncResult(
            status="auth_expired",
            error_message=str(exc),
        )
    except (ConnectionError, OSError):
        log.warning("sync_deadlines_network_error")
        return SyncResult(
            status="network_error",
            error_message="Sync failed — check your connection",
        )
    except Exception as exc:
        log.exception("sync_deadlines_failed")
        return SyncResult(
            status="error",
            error_message=str(exc),
        )


async def record_manual_time_entry(
    app: AppContainer,
    deadline_id: str,
    hours: float,
    *,
    note: str | None = None,
    recorded_at: str | None = None,
) -> None:
    """Record a manual time entry for a deadline."""
    try:
        await _record_time(app.db, deadline_id, hours, note, recorded_at=recorded_at)
    except Exception:
        log.exception("record_manual_time_failed", deadline_id=deadline_id)


async def get_time_entries(
    app: AppContainer,
    deadline_id: str,
) -> list[dict[str, object]]:
    """Fetch all time entries for a deadline, ordered by recorded_at."""
    try:
        cursor = await app.db.execute(
            "SELECT hours, source, note, recorded_at "
            "FROM time_entries WHERE deadline_id = ? ORDER BY recorded_at",
            (deadline_id,),
        )
        rows = await cursor.fetchall()
        return [{"hours": r[0], "source": r[1], "note": r[2], "recorded_at": r[3]} for r in rows]
    except Exception:
        log.exception("get_time_entries_failed", deadline_id=deadline_id)
        return []


async def export_deadlines_ics(
    app: AppContainer,
    *,
    horizon_days: int = 30,
) -> str | None:
    """Export upcoming deadlines as ICS calendar string."""
    try:
        return await _export_deadlines_ics(app.db, horizon_days=horizon_days)
    except Exception:
        log.exception("export_deadlines_ics_failed")
        return None


async def get_past_deadlines(
    app: AppContainer,
    *,
    course_id: int | None = None,
    limit: int = 50,
) -> list[Deadline]:
    """Fetch all past deadlines (completed or past due)."""
    try:
        return await _get_missed_deadlines(app.db, course_id=course_id, limit=limit)
    except Exception:
        log.exception("get_past_deadlines_failed", course_id=course_id)
        return []


async def get_deadline_reflection(
    app: AppContainer,
    deadline_id: str,
) -> dict[str, object] | None:
    """Fetch reflection data for a past deadline (if recorded)."""
    try:
        cursor = await app.db.execute(
            "SELECT predicted_hours, actual_hours, reflection_text "
            "FROM deadline_reflections WHERE deadline_id = ? "
            "ORDER BY rowid DESC LIMIT 1",
            (deadline_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return {
            "predicted_hours": row[0],
            "actual_hours": row[1],
            "reflection_text": row[2],
        }
    except Exception:
        log.exception("get_deadline_reflection_failed", deadline_id=deadline_id)
        return None


# ---------------------------------------------------------------------------
# Effort distribution — pure algorithm + chart config
# ---------------------------------------------------------------------------


@dataclass
class DayEffort:
    """Effort allocation for a single day in the distribution chart."""

    date: str
    deadline_efforts: dict[str, float]
    unestimated: list[str]
    total: float


def compute_effort_distribution(
    *,
    deadlines: list[Deadline],
    estimates: dict[str, float],
    tracked: dict[str, float],
    today: str,
    horizon_days: int = 14,
) -> list[DayEffort]:
    """Distribute remaining effort per deadline evenly across available days.

    Pure function — no DB, no async. Returns one ``DayEffort`` per day that
    has at least one deadline contributing effort or an unestimated entry.
    """
    today_date = date.fromisoformat(today)
    horizon_end = today_date + timedelta(days=horizon_days)

    # Accumulator: date_str → {deadline_name: hours, ...}
    day_efforts: dict[str, dict[str, float]] = {}
    day_unestimated: dict[str, list[str]] = {}

    for dl in deadlines:
        due_date = (
            dl.due_at.date()
            if hasattr(dl.due_at, "date")
            else date.fromisoformat(str(dl.due_at)[:10])
        )

        # Skip past deadlines
        if due_date < today_date:
            continue

        est = estimates.get(dl.id)
        if est is None:
            # Unestimated: mark on each day up to due date
            end = min(due_date, horizon_end - timedelta(days=1))
            d = today_date
            while d <= end:
                ds = d.isoformat()
                day_unestimated.setdefault(ds, []).append(dl.name)
                day_efforts.setdefault(ds, {})
                d += timedelta(days=1)
            continue

        tracked_hours = tracked.get(dl.id, 0.0)
        remaining = max(est - tracked_hours, 0.0)
        if remaining <= 0:
            continue

        # Spread evenly from today to due_date (inclusive), clipped to horizon
        spread_end = min(due_date, horizon_end - timedelta(days=1))
        spread_days: list[str] = []
        d = today_date
        while d <= spread_end:
            spread_days.append(d.isoformat())
            d += timedelta(days=1)

        if not spread_days:
            continue

        per_day = remaining / len(spread_days)
        for ds in spread_days:
            day_efforts.setdefault(ds, {})[dl.name] = round(per_day, 2)

    # Build sorted result
    all_dates = sorted(set(day_efforts) | set(day_unestimated))
    result: list[DayEffort] = []
    for ds in all_dates:
        efforts = day_efforts.get(ds, {})
        total = sum(efforts.values())
        result.append(
            DayEffort(
                date=ds,
                deadline_efforts=efforts,
                unestimated=day_unestimated.get(ds, []),
                total=round(total, 2),
            )
        )
    return result


def build_effort_chart_config(
    days: list[DayEffort],
    *,
    capacity: float = 4.0,
) -> dict[str, Any]:
    """Build an ECharts stacked bar config from distribution data."""
    if not days:
        return {
            "xAxis": {"type": "category", "data": []},
            "yAxis": {"type": "value", "name": "Hours"},
            "series": [],
        }

    dates = [d.date for d in days]
    # Collect all deadline names across all days
    all_names: list[str] = []
    seen: set[str] = set()
    for d in days:
        for name in d.deadline_efforts:
            if name not in seen:
                all_names.append(name)
                seen.add(name)

    has_unestimated = any(d.unestimated for d in days)

    series: list[dict[str, Any]] = []
    for i, name in enumerate(all_names):
        data = [d.deadline_efforts.get(name, 0.0) for d in days]
        entry: dict[str, Any] = {
            "name": name,
            "type": "bar",
            "stack": "effort",
            "data": data,
        }
        # Add capacity markLine on the first series only
        if i == 0:
            entry["markLine"] = {
                "silent": True,
                "data": [
                    {
                        "yAxis": capacity,
                        "name": "Capacity",
                        "lineStyle": {"color": "#e74c3c", "type": "dashed"},
                    }
                ],
            }
        series.append(entry)

    if has_unestimated:
        unest_data: list[float] = []
        for d in days:
            unest_data.append(0.5 if d.unestimated else 0.0)
        entry = {
            "name": "Unestimated",
            "type": "bar",
            "stack": "effort",
            "data": unest_data,
            "itemStyle": {"color": "#bdc3c7"},
            "tooltip": {"formatter": "{b}: {a}"},
        }
        if not series:
            entry["markLine"] = {
                "silent": True,
                "data": [
                    {
                        "yAxis": capacity,
                        "name": "Capacity",
                        "lineStyle": {"color": "#e74c3c", "type": "dashed"},
                    }
                ],
            }
        series.append(entry)

    return {
        "tooltip": {"trigger": "axis"},
        "legend": {"data": [s["name"] for s in series]},
        "xAxis": {"type": "category", "data": dates},
        "yAxis": {"type": "value", "name": "Hours"},
        "series": series,
    }


async def get_effort_distribution_data(
    app: AppContainer,
    *,
    horizon_days: int = 14,
) -> list[DayEffort]:
    """Fetch deadlines + estimates + tracked time, then compute distribution."""
    try:
        deadlines = await _get_deadlines(app.db, horizon_days=horizon_days)

        estimates: dict[str, float] = {}
        tracked_map: dict[str, float] = {}
        for dl in deadlines:
            # Fetch latest estimate
            cursor = await app.db.execute(
                "SELECT predicted_hours FROM effort_estimates "
                "WHERE deadline_id = ? ORDER BY estimated_at DESC LIMIT 1",
                (dl.id,),
            )
            row = await cursor.fetchone()
            if row and row[0] is not None:
                estimates[dl.id] = float(row[0])

            tracked_map[dl.id] = await _get_tracked_time(app.db, dl.id)

        today_str = datetime.now(UTC).strftime("%Y-%m-%d")
        return compute_effort_distribution(
            deadlines=deadlines,
            estimates=estimates,
            tracked=tracked_map,
            today=today_str,
            horizon_days=horizon_days,
        )
    except Exception:
        log.exception("get_effort_distribution_failed")
        return []
