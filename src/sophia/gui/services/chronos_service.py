"""GUI-safe wrappers for Chronos deadline-coach data fetching."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from sophia.services.chronos import (
    compute_priority_score as _compute_priority_score,
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
    start_timer as _start_timer,
)
from sophia.services.chronos import (
    stop_timer as _stop_timer,
)

if TYPE_CHECKING:
    from sophia.domain.models import (
        CalibrationMetrics,
        Deadline,
        DeadlineType,
        EffortEstimate,
        EstimationScaffold,
    )
    from sophia.infra.di import AppContainer

log = structlog.get_logger()


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
