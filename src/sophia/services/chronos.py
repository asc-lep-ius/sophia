"""Chronos deadline-discovery and effort-estimation service."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

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
