"""Chronos deadline-discovery and effort-estimation service."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.domain.errors import ChronosError
from sophia.domain.models import (
    Deadline,
    DeadlineType,
    EffortEstimate,
    EstimationScaffold,
)
from sophia.infra.schema import (
    active_timers,
    deadline_cache,
    deadline_reflections,
    effort_estimates,
    metacognition_log,
    time_entries,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.domain.models import AssignmentInfo, Course, TissExamDate
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

CACHE_STALE_HOURS = 6
COUNT_THRESHOLD_MINIMAL = 10
COUNT_THRESHOLD_OPEN = 25
CALIBRATION_THRESHOLD_ENTRIES = 5
CALIBRATION_HIGH_ERROR = 0.3
CALIBRATION_LOW_ERROR = 0.15
CALIBRATION_VERY_LOW_ERROR = 0.05
REFERENCE_CLASS_MIN_ENTRIES = 3
DEFAULT_IMPORTANCE = 0.5
EFFORT_GAP_MINIMUM = 0.5

_MODULE_TO_DEADLINE_TYPE: dict[str, DeadlineType] = {
    "assign": DeadlineType.ASSIGNMENT,
    "checkmark": DeadlineType.CHECKMARK,
    "quiz": DeadlineType.QUIZ,
}


# ---------------------------------------------------------------------------
# Data conversion helpers
# ---------------------------------------------------------------------------


def _assignment_to_deadline(info: AssignmentInfo, course_name: str) -> Deadline | None:
    if not info.due_date:
        return None
    try:
        due = datetime.fromtimestamp(int(info.due_date), tz=UTC)
    except (ValueError, OverflowError):
        log.warning("invalid_assignment_due_date", id=info.id, due_date=info.due_date)
        return None
    return Deadline(
        id=f"assign:{info.id}",
        name=info.name,
        course_id=info.course_id,
        course_name=course_name,
        deadline_type=DeadlineType.ASSIGNMENT,
        due_at=due,
        submission_status=info.submission_status or None,
        url=info.url,
    )


def _exam_to_deadlines(exam: TissExamDate, course_name: str, course_id: int) -> list[Deadline]:
    deadlines: list[Deadline] = []
    if exam.date_start:
        try:
            due = datetime.fromisoformat(exam.date_start)
            if due.tzinfo is None:
                due = due.replace(tzinfo=UTC)
            deadlines.append(
                Deadline(
                    id=f"exam:{exam.exam_id}",
                    name=exam.title or f"Exam {exam.course_number}",
                    course_id=course_id,
                    course_name=course_name,
                    deadline_type=DeadlineType.EXAM,
                    due_at=due,
                    extra={"mode": exam.mode} if exam.mode else {},
                )
            )
        except ValueError:
            log.warning("invalid_exam_date", exam_id=exam.exam_id, date=exam.date_start)

    if exam.registration_end:
        try:
            reg_due = datetime.fromisoformat(exam.registration_end)
            if reg_due.tzinfo is None:
                reg_due = reg_due.replace(tzinfo=UTC)
            deadlines.append(
                Deadline(
                    id=f"examreg:{exam.exam_id}",
                    name=f"Registration: {exam.title or exam.course_number}",
                    course_id=course_id,
                    course_name=course_name,
                    deadline_type=DeadlineType.EXAM_REGISTRATION,
                    due_at=reg_due,
                )
            )
        except ValueError:
            log.warning("invalid_exam_reg_date", exam_id=exam.exam_id)

    return deadlines


def _extract_course_number(course: Course) -> str | None:
    """Extract TISS course number from course shortname (e.g. '186.813')."""
    shortname = course.shortname or ""
    for part in shortname.replace("-", ".").split():
        if "." in part and any(c.isdigit() for c in part):
            cleaned = part.strip("()")
            if cleaned:
                return cleaned
    # Fallback: the whole shortname might be the number
    if "." in shortname and any(c.isdigit() for c in shortname):
        return shortname.strip()
    return None


def _calendar_event_to_deadline(event: dict[str, Any]) -> Deadline | None:
    """Convert a Moodle calendar action event to a Deadline."""
    modulename = event.get("modulename", "")
    deadline_type = _MODULE_TO_DEADLINE_TYPE.get(modulename)
    if deadline_type is None:
        return None

    timestart = event.get("timestart")
    if not timestart:
        return None

    try:
        due = datetime.fromtimestamp(int(timestart), tz=UTC)
    except (ValueError, OverflowError):
        return None

    course = event.get("course", {})
    course_id = course.get("id", 0)
    course_name = course.get("fullname", "")

    extra: dict[str, Any] = {}
    action = event.get("action", {})
    if action.get("itemcount"):
        extra["item_count"] = action["itemcount"]

    # Use instance (cmid) for ID continuity with scraped assignments
    instance = event.get("instance") or event.get("id", 0)
    deadline_id = f"{modulename}:{instance}"

    name = event.get("name", "")
    # Calendar API appends " ist fällig." to activity names
    name = name.removesuffix(" ist fällig.")

    return Deadline(
        id=deadline_id,
        name=name,
        course_id=course_id,
        course_name=course_name,
        deadline_type=deadline_type,
        due_at=due,
        url=event.get("url"),
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Core service functions
# ---------------------------------------------------------------------------


async def sync_deadlines(app: AppContainer, session: AsyncSession) -> list[Deadline]:
    """Fetch deadlines from all enrolled courses and upsert into cache."""
    courses = await app.moodle.get_enrolled_courses()
    all_deadlines: list[Deadline] = []

    # Primary: calendar API (captures all module types in one call)
    try:
        events = await app.moodle.get_calendar_action_events()
        for event in events:
            d = _calendar_event_to_deadline(event)
            if d:
                all_deadlines.append(d)
    except Exception:
        log.warning("calendar_api_failed_falling_back_to_scraping")
        # Fallback: per-course assignment scraping (original behavior)
        for course in courses:
            try:
                deadlines = await _sync_course_assignments(app, course)
                all_deadlines.extend(deadlines)
            except Exception:
                log.exception(
                    "sync_course_failed",
                    course_id=course.id,
                    course=course.fullname,
                )
                continue

    # TISS exams (not in Moodle calendar — always per-course)
    for course in courses:
        course_name = course.fullname or course.shortname or str(course.id)
        course_number = _extract_course_number(course)
        if course_number:
            try:
                exams = await app.tiss.get_exam_dates(course_number)
                for exam in exams:
                    all_deadlines.extend(_exam_to_deadlines(exam, course_name, course.id))
            except Exception:
                log.warning("tiss_exam_fetch_failed", course_number=course_number)

    await _upsert_deadlines(session, all_deadlines)
    log.info("deadlines_synced", count=len(all_deadlines))
    return all_deadlines


async def _sync_course_assignments(app: AppContainer, course: Course) -> list[Deadline]:
    """Fallback: scrape assignment deadlines for a single course."""
    deadlines: list[Deadline] = []
    course_name = course.fullname or course.shortname or str(course.id)

    try:
        assignments = await app.moodle.get_assignments([course.id])
        for a in assignments:
            d = _assignment_to_deadline(a, course_name)
            if d:
                deadlines.append(d)
    except Exception:
        log.warning("assignments_fetch_failed", course_id=course.id)

    return deadlines


async def _upsert_deadlines(session: AsyncSession, deadlines: list[Deadline]) -> None:
    """Upsert deadlines into the cache table."""
    for d in deadlines:
        values = {
            "name": d.name,
            "course_id": d.course_id,
            "course_name": d.course_name,
            "deadline_type": d.deadline_type.value,
            "due_at": d.due_at.isoformat(),
            "grade_weight": d.grade_weight,
            "submission_status": d.submission_status,
            "url": d.url,
            "extra": json.dumps(d.extra),
            "synced_at": datetime.now(UTC).isoformat(),
        }
        statement = pg_insert(deadline_cache).values(id=d.id, **values)
        await session.execute(
            statement.on_conflict_do_update(
                index_elements=[deadline_cache.c.id],
                set_={key: statement.excluded[key] for key in values},
            )
        )


async def get_deadlines(
    session: AsyncSession,
    *,
    course_id: int | None = None,
    horizon_days: int = 14,
) -> list[Deadline]:
    """Load upcoming deadlines from cache within the given horizon."""
    now = datetime.now(UTC)
    query = (
        select(deadline_cache)
        .where(
            deadline_cache.c.due_at > now.isoformat(),
            deadline_cache.c.due_at < (now + timedelta(days=horizon_days)).isoformat(),
        )
        .order_by(deadline_cache.c.due_at.asc())
    )
    if course_id is not None:
        query = query.where(deadline_cache.c.course_id == course_id)

    rows = (await session.execute(query)).all()
    await _warn_if_stale(session)

    return [
        Deadline(
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
        for row in rows
    ]


async def _warn_if_stale(session: AsyncSession) -> None:
    """Log when the cache has not been synced recently."""
    last_synced = await session.scalar(select(func.max(deadline_cache.c.synced_at)))
    if not last_synced:
        return
    try:
        last_sync = datetime.fromisoformat(last_synced)
    except ValueError:
        return
    if last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=UTC)
    if datetime.now(UTC) - last_sync > timedelta(hours=CACHE_STALE_HOURS):
        log.warning("deadline_cache_stale", last_sync=last_synced)


def _effort_log_query(deadline_type: DeadlineType, course_id: int | None):
    """Base query over the effort rows of the metacognition log."""
    query = select(metacognition_log).where(
        metacognition_log.c.domain == f"effort:{deadline_type.value}",
    )
    if course_id is not None:
        query = query.where(metacognition_log.c.course_id == str(course_id))
    return query


async def get_scaffold_level(
    session: AsyncSession,
    deadline_type: DeadlineType,
    *,
    course_id: int | None = None,
) -> EstimationScaffold:
    """Determine scaffold level based on calibration accuracy or count fallback."""
    cal_rows = (
        await session.execute(
            _effort_log_query(deadline_type, course_id).where(
                metacognition_log.c.actual.is_not(None),
            )
        )
    ).all()

    if len(cal_rows) >= CALIBRATION_THRESHOLD_ENTRIES:
        # Calibration-based scaffold
        total_error = sum(
            abs(row.predicted - row.actual) / max(row.actual, 0.1) for row in cal_rows
        )
        mean_error = total_error / len(cal_rows)

        if mean_error > CALIBRATION_HIGH_ERROR:
            return EstimationScaffold.FULL
        if mean_error >= CALIBRATION_VERY_LOW_ERROR:
            return EstimationScaffold.MINIMAL
        return EstimationScaffold.OPEN

    # Count-based fallback: how many estimates exist
    count_query = select(func.count()).select_from(effort_estimates)
    if course_id is not None:
        count_query = count_query.where(effort_estimates.c.course_id == course_id)
    count = await session.scalar(count_query) or 0

    if count >= COUNT_THRESHOLD_OPEN:
        return EstimationScaffold.OPEN
    if count >= COUNT_THRESHOLD_MINIMAL:
        return EstimationScaffold.MINIMAL
    return EstimationScaffold.FULL


async def get_reference_class(
    session: AsyncSession,
    deadline_type: DeadlineType,
    *,
    course_id: int | None = None,
) -> list[tuple[float, float | None]]:
    """Past effort estimates + actuals for this deadline type.

    Returns list of (predicted, actual) tuples.
    """
    rows = (await session.execute(_effort_log_query(deadline_type, course_id))).all()
    return [(row.predicted, row.actual) for row in rows]


async def format_reference_class_hint(
    session: AsyncSession,
    deadline_type: DeadlineType,
    *,
    course_id: int | None = None,
) -> str | None:
    """Format past actual times for display. None if <3 historical entries."""
    rows = (
        await session.execute(
            _effort_log_query(deadline_type, course_id).where(
                metacognition_log.c.actual.is_not(None),
            )
        )
    ).all()

    if len(rows) < REFERENCE_CLASS_MIN_ENTRIES:
        return None

    actuals = [row.actual for row in rows]
    avg = sum(actuals) / len(actuals)
    low = min(actuals)
    high = max(actuals)

    return (
        f"Past {deadline_type.value}s took {low:.1f}–{high:.1f} hours "
        f"(avg {avg:.1f} hours, n={len(actuals)})"
    )


async def record_estimate(
    session: AsyncSession,
    *,
    deadline_id: str,
    course_id: int,
    predicted_hours: float,
    breakdown: dict[str, float] | None = None,
    intention: str | None = None,
) -> EffortEstimate:
    """Store an effort estimate and write to metacognition_log."""
    # Look up deadline type from cache
    stored_type = await session.scalar(
        select(deadline_cache.c.deadline_type).where(deadline_cache.c.id == deadline_id)
    )
    deadline_type = DeadlineType(stored_type) if stored_type else DeadlineType.ASSIGNMENT

    scaffold = await get_scaffold_level(session, deadline_type, course_id=course_id)
    now = datetime.now(UTC).isoformat()

    await session.execute(
        insert(effort_estimates).values(
            deadline_id=deadline_id,
            course_id=course_id,
            predicted_hours=predicted_hours,
            breakdown=json.dumps(breakdown) if breakdown else None,
            implementation_intention=intention,
            scaffold_level=scaffold.value,
            estimated_at=now,
        )
    )

    # Write to metacognition_log for calibration tracking
    statement = pg_insert(metacognition_log).values(
        domain=f"effort:{deadline_type.value}",
        item_id=deadline_id,
        predicted=predicted_hours,
        predicted_at=datetime.now(UTC),
        course_id=str(course_id),
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[metacognition_log.c.domain, metacognition_log.c.item_id],
            set_={
                "predicted": statement.excluded.predicted,
                "predicted_at": statement.excluded.predicted_at,
                "course_id": statement.excluded.course_id,
                # A new prediction voids the old outcome. Keeping it would pair
                # this estimate with an actual measured against a different one,
                # and get_calibration_metrics would score that as real data.
                "actual": None,
                "actual_at": None,
            },
        )
    )

    log.info(
        "effort_estimated",
        deadline_id=deadline_id,
        hours=predicted_hours,
        scaffold=scaffold.value,
    )

    return EffortEstimate(
        deadline_id=deadline_id,
        course_id=course_id,
        predicted_hours=predicted_hours,
        breakdown=breakdown,
        implementation_intention=intention,
        scaffold_level=scaffold,
        estimated_at=now,
    )


# ---------------------------------------------------------------------------
# Time tracking
# ---------------------------------------------------------------------------

UNDERESTIMATE_RATIO_MINOR = 1.25
UNDERESTIMATE_RATIO_MAJOR = 2.0
OVERESTIMATE_RATIO = 0.75


async def start_timer(session: AsyncSession, deadline_id: str) -> None:
    """Start a timer for a deadline. Raises ChronosError if already running."""
    running = await session.scalar(
        select(active_timers.c.deadline_id).where(active_timers.c.deadline_id == deadline_id)
    )
    if running is not None:
        raise ChronosError(f"Timer already running for {deadline_id}")

    await session.execute(
        insert(active_timers).values(
            deadline_id=deadline_id,
            started_at=datetime.now(UTC).isoformat(),
        )
    )
    log.info("timer_started", deadline_id=deadline_id)


async def stop_timer(session: AsyncSession, deadline_id: str) -> float:
    """Stop running timer, record elapsed hours as a time entry. Returns hours."""
    started_at = await session.scalar(
        select(active_timers.c.started_at).where(active_timers.c.deadline_id == deadline_id)
    )
    if not started_at:
        raise ChronosError(f"No timer running for {deadline_id}")

    started = datetime.fromisoformat(started_at)
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - started).total_seconds() / 3600.0

    await session.execute(delete(active_timers).where(active_timers.c.deadline_id == deadline_id))
    await session.execute(
        insert(time_entries).values(deadline_id=deadline_id, hours=elapsed, source="timer")
    )
    log.info("timer_stopped", deadline_id=deadline_id, hours=round(elapsed, 2))
    return elapsed


async def record_time(
    session: AsyncSession,
    deadline_id: str,
    hours: float,
    note: str | None = None,
    *,
    recorded_at: str | None = None,
) -> None:
    """Record a manual time entry."""
    await session.execute(
        insert(time_entries).values(
            deadline_id=deadline_id,
            hours=hours,
            source="manual",
            note=note,
            recorded_at=recorded_at or datetime.now(UTC).isoformat(),
        )
    )
    log.info("time_recorded", deadline_id=deadline_id, hours=hours)


async def latest_estimate(session: AsyncSession, deadline_id: str) -> float | None:
    """Most recent predicted hours for a deadline, or None when never estimated."""
    predicted = await session.scalar(
        select(effort_estimates.c.predicted_hours)
        .where(effort_estimates.c.deadline_id == deadline_id)
        .order_by(effort_estimates.c.estimated_at.desc())
        .limit(1)
    )
    return None if predicted is None else float(predicted)


async def get_tracked_time(session: AsyncSession, deadline_id: str) -> float:
    """Sum all time entries (timer + manual) for a deadline."""
    total = await session.scalar(
        select(func.coalesce(func.sum(time_entries.c.hours), 0.0)).where(
            time_entries.c.deadline_id == deadline_id,
        )
    )
    return float(total or 0.0)


# ---------------------------------------------------------------------------
# Post-deadline reflection
# ---------------------------------------------------------------------------


async def record_reflection(
    session: AsyncSession,
    deadline_id: str,
    *,
    predicted_hours: float | None,
    actual_hours: float,
    reflection_text: str,
) -> None:
    """Store post-deadline reflection text."""
    await session.execute(
        insert(deadline_reflections).values(
            deadline_id=deadline_id,
            predicted_hours=predicted_hours,
            actual_hours=actual_hours,
            reflection_text=reflection_text,
        )
    )
    log.info("reflection_recorded", deadline_id=deadline_id)


async def complete_deadline(
    session: AsyncSession,
    deadline_id: str,
) -> tuple[float | None, float, str]:
    """Mark deadline done: get predicted & actual hours, update metacognition_log.

    Returns (predicted_hours, actual_hours, formatted_feedback).
    """
    actual_hours = await get_tracked_time(session, deadline_id)

    # Look up deadline_type for metacognition domain
    cached = (
        await session.execute(
            select(deadline_cache.c.deadline_type, deadline_cache.c.course_id).where(
                deadline_cache.c.id == deadline_id,
            )
        )
    ).one_or_none()
    deadline_type = DeadlineType(cached.deadline_type) if cached else DeadlineType.ASSIGNMENT
    course_id = int(cached.course_id) if cached and cached.course_id is not None else None

    # Get predicted from effort_estimates
    predicted = await session.scalar(
        select(effort_estimates.c.predicted_hours)
        .where(effort_estimates.c.deadline_id == deadline_id)
        .order_by(effort_estimates.c.estimated_at.desc())
        .limit(1)
    )
    predicted_hours = float(predicted) if predicted is not None else None

    # Update metacognition_log with actual
    values: dict[str, object] = {"actual": actual_hours, "actual_at": datetime.now(UTC)}
    if course_id is not None:
        values["course_id"] = str(course_id)
    await session.execute(
        update(metacognition_log)
        .where(
            metacognition_log.c.domain == f"effort:{deadline_type.value}",
            metacognition_log.c.item_id == deadline_id,
        )
        .values(**values)
    )

    feedback = format_estimation_feedback(predicted_hours, actual_hours)
    log.info(
        "deadline_completed",
        deadline_id=deadline_id,
        predicted=predicted_hours,
        actual=actual_hours,
    )
    return predicted_hours, actual_hours, feedback


def format_estimation_feedback(predicted: float | None, actual: float) -> str:
    """Empathetic, constructivist feedback on estimation accuracy.

    Never guilt-frames. Normalizes errors and emphasizes growth.
    """
    if predicted is None:
        return f"📊 Tracked {actual:.1f}h total — no estimate to compare against."

    ratio = actual / predicted if predicted > 0 else float("inf")

    if ratio <= UNDERESTIMATE_RATIO_MINOR and ratio >= OVERESTIMATE_RATIO:
        return (
            f"✅ Well calibrated! ({predicted:.1f}h predicted, {actual:.1f}h actual) "
            "— your estimation sense is solid here."
        )

    if ratio > UNDERESTIMATE_RATIO_MAJOR:
        return (
            f"🔍 {predicted:.1f}h predicted, {actual:.1f}h actual — "
            "This is a very common pattern. Most students underestimate by ~2× "
            "on their first few tasks. This gap is your biggest learning opportunity."
        )

    if ratio > UNDERESTIMATE_RATIO_MINOR:
        return (
            f"🔍 {predicted:.1f}h predicted, {actual:.1f}h actual — "
            "Slightly under. Breaking tasks into smaller phases can help close this gap."
        )

    # Overestimate (ratio < OVERESTIMATE_RATIO)
    return (
        f"💪 {predicted:.1f}h predicted, {actual:.1f}h actual — "
        "You were faster than you thought! Overestimation is common early on "
        "and usually self-corrects."
    )


# ---------------------------------------------------------------------------
# Priority scoring + workload forecast
# ---------------------------------------------------------------------------


def compute_priority_score(
    deadline: Deadline,
    estimated_hours: float | None,
    tracked_hours: float,
    confidence_multiplier: float = 1.0,
) -> dict[str, float]:
    """Compute composite priority with transparent components.

    Returns dict with urgency, importance, effort_gap, confidence_multiplier,
    and score so students see WHY something ranks as it does.
    """
    hours_until_due = (deadline.due_at - datetime.now(UTC)).total_seconds() / 3600.0
    urgency = 1.0 / max(hours_until_due, 1.0)

    importance = deadline.grade_weight if deadline.grade_weight is not None else DEFAULT_IMPORTANCE

    if estimated_hours is not None:
        effort_gap = max(estimated_hours - tracked_hours, EFFORT_GAP_MINIMUM)
    else:
        effort_gap = EFFORT_GAP_MINIMUM

    return {
        "urgency": urgency,
        "importance": importance,
        "effort_gap": effort_gap,
        "confidence_multiplier": confidence_multiplier,
        "score": urgency * importance * effort_gap * confidence_multiplier,
    }


async def get_workload_forecast(
    session: AsyncSession,
    *,
    course_id: int | None = None,
    horizon_days: int = 7,
) -> dict[str, object]:
    """Compute workload summary for the horizon window."""
    now = datetime.now(UTC)
    horizon_end = now + timedelta(days=horizon_days)

    latest_estimate = (
        select(effort_estimates.c.predicted_hours)
        .where(effort_estimates.c.deadline_id == deadline_cache.c.id)
        .order_by(effort_estimates.c.estimated_at.desc())
        .limit(1)
        .scalar_subquery()
    )
    query = (
        select(
            deadline_cache.c.id,
            deadline_cache.c.name,
            deadline_cache.c.due_at,
            latest_estimate.label("est_hours"),
        )
        .where(
            deadline_cache.c.due_at > now.isoformat(),
            deadline_cache.c.due_at < horizon_end.isoformat(),
        )
        .order_by(deadline_cache.c.due_at.asc())
    )
    if course_id is not None:
        query = query.where(deadline_cache.c.course_id == course_id)

    rows = (await session.execute(query)).all()

    total_estimated = 0.0
    total_tracked = 0.0
    per_day: dict[str, list[tuple[str, float]]] = {}

    for row in rows:
        deadline_id, name, due_at_str = row.id, row.name, row.due_at
        est = float(row.est_hours) if row.est_hours is not None else 0.0

        tracked = await get_tracked_time(session, deadline_id)

        total_estimated += est
        total_tracked += tracked
        remaining = max(est - tracked, 0.0)

        due_date = datetime.fromisoformat(due_at_str).strftime("%Y-%m-%d")
        per_day.setdefault(due_date, []).append((name, remaining))

    return {
        "total_estimated_hours": total_estimated,
        "total_tracked_hours": total_tracked,
        "remaining_hours": max(total_estimated - total_tracked, 0.0),
        "deadline_count": len(rows),
        "per_day": per_day,
    }


# Re-export from chronos_export for backward compatibility
from sophia.services.chronos_export import (  # noqa: E402
    export_deadlines_ics,
    get_calibration_metrics,
    get_missed_deadlines,
    get_upcoming_exams,
)

__all__ = [
    "export_deadlines_ics",
    "get_calibration_metrics",
    "get_missed_deadlines",
    "get_upcoming_exams",
]
