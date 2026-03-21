"""Chronos deadline-discovery and effort-estimation service."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from sophia.domain.errors import ChronosError
from sophia.domain.models import (
    Deadline,
    DeadlineType,
    EffortEstimate,
    EstimationScaffold,
)

if TYPE_CHECKING:
    import aiosqlite

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


# ---------------------------------------------------------------------------
# Core service functions
# ---------------------------------------------------------------------------


async def sync_deadlines(app: AppContainer) -> list[Deadline]:
    """Fetch deadlines from all enrolled courses and upsert into cache."""
    courses = await app.moodle.get_enrolled_courses()
    all_deadlines: list[Deadline] = []

    for course in courses:
        try:
            deadlines = await _sync_course(app, course)
            all_deadlines.extend(deadlines)
        except Exception:
            log.exception("sync_course_failed", course_id=course.id, course=course.fullname)
            continue

    await _upsert_deadlines(app.db, all_deadlines)
    log.info("deadlines_synced", count=len(all_deadlines))
    return all_deadlines


async def _sync_course(app: AppContainer, course: Course) -> list[Deadline]:
    """Gather deadlines for a single course from Moodle + TISS."""
    deadlines: list[Deadline] = []
    course_name = course.fullname or course.shortname or str(course.id)

    # Moodle assignments
    try:
        assignments = await app.moodle.get_assignments([course.id])
        for a in assignments:
            d = _assignment_to_deadline(a, course_name)
            if d:
                deadlines.append(d)
    except Exception:
        log.warning("assignments_fetch_failed", course_id=course.id)

    # Moodle checkmarks (no due_date field — skip for deadline purposes)
    # CheckmarkInfo doesn't have a due_date, so we can't create deadlines from it.

    # TISS exams
    course_number = _extract_course_number(course)
    if course_number:
        try:
            exams = await app.tiss.get_exam_dates(course_number)
            for exam in exams:
                deadlines.extend(_exam_to_deadlines(exam, course_name, course.id))
        except Exception:
            log.warning("tiss_exam_fetch_failed", course_number=course_number)

    return deadlines


async def _upsert_deadlines(db: aiosqlite.Connection, deadlines: list[Deadline]) -> None:
    """Upsert deadlines into the cache table."""
    for d in deadlines:
        await db.execute(
            "INSERT OR REPLACE INTO deadline_cache "
            "(id, name, course_id, course_name, deadline_type, due_at, "
            "grade_weight, submission_status, url, extra, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                d.id,
                d.name,
                d.course_id,
                d.course_name,
                d.deadline_type.value,
                d.due_at.isoformat(),
                d.grade_weight,
                d.submission_status,
                d.url,
                json.dumps(d.extra),
                datetime.now(UTC).isoformat(),
            ),
        )
    await db.commit()


async def get_deadlines(
    db: aiosqlite.Connection,
    *,
    course_id: int | None = None,
    horizon_days: int = 14,
) -> list[Deadline]:
    """Load upcoming deadlines from cache within the given horizon."""
    now = datetime.now(UTC).isoformat()
    horizon_end = (datetime.now(UTC) + timedelta(days=horizon_days)).isoformat()

    query = (
        "SELECT id, name, course_id, course_name, deadline_type, due_at, "
        "grade_weight, submission_status, url, extra "
        "FROM deadline_cache "
        "WHERE due_at > ? AND due_at < ? "
    )
    params: list[str | int] = [now, horizon_end]

    if course_id is not None:
        query += "AND course_id = ? "
        params.append(course_id)

    query += "ORDER BY due_at ASC"

    cursor = await db.execute(query, params)
    rows = list(await cursor.fetchall())

    # Warn if cache is stale
    stale_cursor = await db.execute("SELECT MAX(synced_at) FROM deadline_cache")
    stale_row = await stale_cursor.fetchone()
    if stale_row and stale_row[0]:
        try:
            last_sync = datetime.fromisoformat(stale_row[0])
            if last_sync.tzinfo is None:
                last_sync = last_sync.replace(tzinfo=UTC)
            if datetime.now(UTC) - last_sync > timedelta(hours=CACHE_STALE_HOURS):
                log.warning("deadline_cache_stale", last_sync=stale_row[0])
        except ValueError:
            pass

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
        for row in rows
    ]


async def get_scaffold_level(
    db: aiosqlite.Connection,
    deadline_type: DeadlineType,
    *,
    course_id: int | None = None,
) -> EstimationScaffold:
    """Determine scaffold level based on calibration accuracy or count fallback."""
    domain = f"effort:{deadline_type.value}"

    # Check metacognition_log for calibration data
    cursor = await db.execute(
        "SELECT predicted, actual FROM metacognition_log WHERE domain = ? AND actual IS NOT NULL",
        (domain,),
    )
    cal_rows = list(await cursor.fetchall())

    if len(cal_rows) >= CALIBRATION_THRESHOLD_ENTRIES:
        # Calibration-based scaffold
        total_error = sum(abs(r[0] - r[1]) / max(r[1], 0.1) for r in cal_rows)
        mean_error = total_error / len(cal_rows)

        if mean_error > CALIBRATION_HIGH_ERROR:
            return EstimationScaffold.FULL
        if mean_error >= CALIBRATION_VERY_LOW_ERROR:
            return EstimationScaffold.MINIMAL
        return EstimationScaffold.OPEN

    # Count-based fallback: how many estimates exist
    count_cursor = await db.execute(
        "SELECT COUNT(*) FROM effort_estimates",
    )
    count_row = await count_cursor.fetchone()
    count = count_row[0] if count_row else 0

    if count >= COUNT_THRESHOLD_OPEN:
        return EstimationScaffold.OPEN
    if count >= COUNT_THRESHOLD_MINIMAL:
        return EstimationScaffold.MINIMAL
    return EstimationScaffold.FULL


async def get_reference_class(
    db: aiosqlite.Connection,
    deadline_type: DeadlineType,
    *,
    course_id: int | None = None,
) -> list[tuple[float, float | None]]:
    """Past effort estimates + actuals for this deadline type.

    Returns list of (predicted, actual) tuples.
    """
    domain = f"effort:{deadline_type.value}"
    cursor = await db.execute(
        "SELECT predicted, actual FROM metacognition_log WHERE domain = ?",
        (domain,),
    )
    return list(await cursor.fetchall())  # type: ignore[return-value]


async def format_reference_class_hint(
    db: aiosqlite.Connection,
    deadline_type: DeadlineType,
    *,
    course_id: int | None = None,
) -> str | None:
    """Format past actual times for display. None if <3 historical entries."""
    domain = f"effort:{deadline_type.value}"
    cursor = await db.execute(
        "SELECT actual FROM metacognition_log WHERE domain = ? AND actual IS NOT NULL",
        (domain,),
    )
    rows = list(await cursor.fetchall())

    if len(rows) < REFERENCE_CLASS_MIN_ENTRIES:
        return None

    actuals = [r[0] for r in rows]
    avg = sum(actuals) / len(actuals)
    low = min(actuals)
    high = max(actuals)

    return (
        f"Past {deadline_type.value}s took {low:.1f}–{high:.1f} hours "
        f"(avg {avg:.1f} hours, n={len(actuals)})"
    )


async def record_estimate(
    app: AppContainer,
    *,
    deadline_id: str,
    course_id: int,
    predicted_hours: float,
    breakdown: dict[str, float] | None = None,
    intention: str | None = None,
) -> EffortEstimate:
    """Store an effort estimate and write to metacognition_log."""
    db = app.db

    # Look up deadline type from cache
    cursor = await db.execute(
        "SELECT deadline_type FROM deadline_cache WHERE id = ?",
        (deadline_id,),
    )
    row = await cursor.fetchone()
    deadline_type = DeadlineType(row[0]) if row else DeadlineType.ASSIGNMENT

    scaffold = await get_scaffold_level(db, deadline_type, course_id=course_id)
    now = datetime.now(UTC).isoformat()

    await db.execute(
        "INSERT INTO effort_estimates "
        "(deadline_id, course_id, predicted_hours, breakdown, "
        "implementation_intention, scaffold_level, estimated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            deadline_id,
            course_id,
            predicted_hours,
            json.dumps(breakdown) if breakdown else None,
            intention,
            scaffold.value,
            now,
        ),
    )

    # Write to metacognition_log for calibration tracking
    domain = f"effort:{deadline_type.value}"
    await db.execute(
        "INSERT OR REPLACE INTO metacognition_log "
        "(domain, item_id, predicted, predicted_at) VALUES (?, ?, ?, ?)",
        (domain, deadline_id, predicted_hours, now),
    )

    await db.commit()
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


async def start_timer(db: aiosqlite.Connection, deadline_id: str) -> None:
    """Start a timer for a deadline. Raises ChronosError if already running."""
    cursor = await db.execute("SELECT 1 FROM active_timers WHERE deadline_id = ?", (deadline_id,))
    if await cursor.fetchone():
        raise ChronosError(f"Timer already running for {deadline_id}")

    await db.execute(
        "INSERT INTO active_timers (deadline_id, started_at) VALUES (?, ?)",
        (deadline_id, datetime.now(UTC).isoformat()),
    )
    await db.commit()
    log.info("timer_started", deadline_id=deadline_id)


async def stop_timer(db: aiosqlite.Connection, deadline_id: str) -> float:
    """Stop running timer, record elapsed hours as a time entry. Returns hours."""
    cursor = await db.execute(
        "SELECT started_at FROM active_timers WHERE deadline_id = ?", (deadline_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise ChronosError(f"No timer running for {deadline_id}")

    started = datetime.fromisoformat(row[0])
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - started).total_seconds() / 3600.0

    await db.execute("DELETE FROM active_timers WHERE deadline_id = ?", (deadline_id,))
    await db.execute(
        "INSERT INTO time_entries (deadline_id, hours, source) VALUES (?, ?, ?)",
        (deadline_id, elapsed, "timer"),
    )
    await db.commit()
    log.info("timer_stopped", deadline_id=deadline_id, hours=round(elapsed, 2))
    return elapsed


async def record_time(
    db: aiosqlite.Connection,
    deadline_id: str,
    hours: float,
    note: str | None = None,
) -> None:
    """Record a manual time entry."""
    await db.execute(
        "INSERT INTO time_entries (deadline_id, hours, source, note) VALUES (?, ?, ?, ?)",
        (deadline_id, hours, "manual", note),
    )
    await db.commit()
    log.info("time_recorded", deadline_id=deadline_id, hours=hours)


async def get_tracked_time(db: aiosqlite.Connection, deadline_id: str) -> float:
    """Sum all time entries (timer + manual) for a deadline."""
    cursor = await db.execute(
        "SELECT COALESCE(SUM(hours), 0) FROM time_entries WHERE deadline_id = ?",
        (deadline_id,),
    )
    row = await cursor.fetchone()
    return float(row[0]) if row else 0.0


# ---------------------------------------------------------------------------
# Post-deadline reflection
# ---------------------------------------------------------------------------


async def record_reflection(
    db: aiosqlite.Connection,
    deadline_id: str,
    *,
    predicted_hours: float | None,
    actual_hours: float,
    reflection_text: str,
) -> None:
    """Store post-deadline reflection text."""
    await db.execute(
        "INSERT INTO deadline_reflections "
        "(deadline_id, predicted_hours, actual_hours, reflection_text) "
        "VALUES (?, ?, ?, ?)",
        (deadline_id, predicted_hours, actual_hours, reflection_text),
    )
    await db.commit()
    log.info("reflection_recorded", deadline_id=deadline_id)


async def complete_deadline(
    app: AppContainer,
    deadline_id: str,
) -> tuple[float | None, float, str]:
    """Mark deadline done: get predicted & actual hours, update metacognition_log.

    Returns (predicted_hours, actual_hours, formatted_feedback).
    """
    db = app.db
    actual_hours = await get_tracked_time(db, deadline_id)

    # Look up deadline_type for metacognition domain
    cursor = await db.execute(
        "SELECT deadline_type FROM deadline_cache WHERE id = ?", (deadline_id,)
    )
    row = await cursor.fetchone()
    deadline_type = DeadlineType(row[0]) if row else DeadlineType.ASSIGNMENT

    # Get predicted from effort_estimates
    cursor = await db.execute(
        "SELECT predicted_hours FROM effort_estimates WHERE deadline_id = ? "
        "ORDER BY estimated_at DESC LIMIT 1",
        (deadline_id,),
    )
    est_row = await cursor.fetchone()
    predicted_hours = float(est_row[0]) if est_row else None

    # Update metacognition_log with actual
    domain = f"effort:{deadline_type.value}"
    await db.execute(
        "UPDATE metacognition_log SET actual = ?, actual_at = ? WHERE domain = ? AND item_id = ?",
        (actual_hours, datetime.now(UTC).isoformat(), domain, deadline_id),
    )
    await db.commit()

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
) -> dict[str, float]:
    """Compute composite priority with transparent components.

    Returns dict with urgency, importance, effort_gap, and score so
    students see WHY something ranks as it does.
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
        "score": urgency * importance * effort_gap,
    }


async def get_workload_forecast(
    db: aiosqlite.Connection,
    horizon_days: int = 7,
) -> dict[str, object]:
    """Compute workload summary for the horizon window."""
    now = datetime.now(UTC)
    horizon_end = now + timedelta(days=horizon_days)

    cursor = await db.execute(
        "SELECT dc.id, dc.name, dc.due_at, "
        "  (SELECT e.predicted_hours FROM effort_estimates e "
        "   WHERE e.deadline_id = dc.id ORDER BY e.estimated_at DESC LIMIT 1) AS est_hours "
        "FROM deadline_cache dc "
        "WHERE dc.due_at > ? AND dc.due_at < ? "
        "ORDER BY dc.due_at ASC",
        (now.isoformat(), horizon_end.isoformat()),
    )
    rows = list(await cursor.fetchall())

    total_estimated = 0.0
    total_tracked = 0.0
    per_day: dict[str, list[tuple[str, float]]] = {}

    for row in rows:
        deadline_id, name, due_at_str, est_hours = row
        est = float(est_hours) if est_hours is not None else 0.0

        tracked_cursor = await db.execute(
            "SELECT COALESCE(SUM(hours), 0) FROM time_entries WHERE deadline_id = ?",
            (deadline_id,),
        )
        tracked_row = await tracked_cursor.fetchone()
        tracked = float(tracked_row[0]) if tracked_row else 0.0

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
