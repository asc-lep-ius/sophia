"""Tests for the Chronos deadline-discovery and effort-estimation service."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from sophia.domain.models import (
    AssignmentInfo,
    Course,
    Deadline,
    DeadlineType,
    EffortEstimate,
    EstimationScaffold,
    TissExamDate,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    """In-memory SQLite with initial + chronos migrations applied."""
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.executescript(Path("src/sophia/infra/migrations/001_initial.sql").read_text())
    await conn.executescript(Path("src/sophia/infra/migrations/017_chronos.sql").read_text())
    await conn.executescript(Path("src/sophia/infra/migrations/018_chronos_time.sql").read_text())
    await conn.commit()
    yield conn
    await conn.close()


@pytest.fixture
def app_container(db: aiosqlite.Connection) -> MagicMock:
    """Minimal AppContainer mock wired to the in-memory DB."""
    container = MagicMock()
    container.db = db
    container.moodle = AsyncMock()
    container.tiss = AsyncMock()
    return container


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FUTURE = datetime.now(UTC) + timedelta(days=5)
PAST = datetime.now(UTC) - timedelta(days=2)
FAR_FUTURE = datetime.now(UTC) + timedelta(days=30)


def _unix_ts(dt: datetime) -> str:
    return str(int(dt.timestamp()))


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def _insert_deadline(
    db: aiosqlite.Connection,
    *,
    id: str = "assign:1",
    name: str = "HW1",
    course_id: int = 42,
    course_name: str = "Algorithms",
    deadline_type: str = "assignment",
    due_at: str | None = None,
    synced_at: str | None = None,
) -> None:
    due = due_at or _iso(FUTURE)
    synced = synced_at or datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO deadline_cache "
        "(id, name, course_id, course_name, deadline_type, due_at, synced_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (id, name, course_id, course_name, deadline_type, due, synced),
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Domain model tests
# ---------------------------------------------------------------------------


class TestDeadlineModel:
    def test_create_deadline(self) -> None:
        d = Deadline(
            id="assign:1",
            name="HW1",
            course_id=42,
            course_name="Algorithms",
            deadline_type=DeadlineType.ASSIGNMENT,
            due_at=FUTURE,
        )
        assert d.id == "assign:1"
        assert d.deadline_type == DeadlineType.ASSIGNMENT
        assert d.grade_weight is None

    def test_deadline_frozen(self) -> None:
        d = Deadline(
            id="assign:1",
            name="HW1",
            course_id=42,
            course_name="Algo",
            deadline_type=DeadlineType.ASSIGNMENT,
            due_at=FUTURE,
        )
        with pytest.raises(Exception):  # noqa: B017
            d.name = "changed"  # type: ignore[misc]


class TestEffortEstimateModel:
    def test_create_estimate(self) -> None:
        e = EffortEstimate(
            deadline_id="assign:1",
            course_id=42,
            predicted_hours=3.0,
            scaffold_level=EstimationScaffold.FULL,
            estimated_at=datetime.now(UTC).isoformat(),
        )
        assert e.predicted_hours == 3.0
        assert e.scaffold_level == EstimationScaffold.FULL

    def test_estimate_with_breakdown(self) -> None:
        breakdown = {"reading": 1.5, "coding": 1.5}
        e = EffortEstimate(
            deadline_id="assign:1",
            course_id=42,
            predicted_hours=3.0,
            breakdown=breakdown,
            scaffold_level=EstimationScaffold.MINIMAL,
            estimated_at=datetime.now(UTC).isoformat(),
        )
        assert e.breakdown == breakdown


class TestDeadlineTypeEnum:
    def test_values(self) -> None:
        assert DeadlineType.ASSIGNMENT == "assignment"
        assert DeadlineType.QUIZ == "quiz"
        assert DeadlineType.EXAM == "exam"
        assert DeadlineType.EXAM_REGISTRATION == "exam_registration"

    def test_scaffold_levels(self) -> None:
        assert EstimationScaffold.FULL == "full"
        assert EstimationScaffold.MINIMAL == "minimal"
        assert EstimationScaffold.OPEN == "open"


# ---------------------------------------------------------------------------
# sync_deadlines
# ---------------------------------------------------------------------------


class TestSyncDeadlines:
    async def test_syncs_assignments(self, app_container: MagicMock) -> None:
        from sophia.services.chronos import sync_deadlines

        app_container.moodle.get_enrolled_courses = AsyncMock(
            return_value=[Course(id=42, fullname="Algorithms", shortname="186.813")]
        )
        app_container.moodle.get_assignments = AsyncMock(
            return_value=[
                AssignmentInfo(
                    id=1,
                    name="HW1",
                    course_id=42,
                    due_date=_unix_ts(FUTURE),
                )
            ]
        )
        app_container.moodle.get_checkmarks = AsyncMock(return_value=[])
        app_container.tiss.get_exam_dates = AsyncMock(return_value=[])

        result = await sync_deadlines(app_container)

        assert len(result) == 1
        assert result[0].id == "assign:1"
        assert result[0].deadline_type == DeadlineType.ASSIGNMENT

        # Verify DB persistence
        cursor = await app_container.db.execute("SELECT id, name FROM deadline_cache")
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "assign:1"

    async def test_syncs_tiss_exams(self, app_container: MagicMock) -> None:
        from sophia.services.chronos import sync_deadlines

        app_container.moodle.get_enrolled_courses = AsyncMock(
            return_value=[Course(id=42, fullname="Algorithms", shortname="186.813")]
        )
        app_container.moodle.get_assignments = AsyncMock(return_value=[])
        app_container.moodle.get_checkmarks = AsyncMock(return_value=[])
        app_container.tiss.get_exam_dates = AsyncMock(
            return_value=[
                TissExamDate(
                    exam_id="E1",
                    course_number="186.813",
                    title="Final",
                    date_start=_iso(FUTURE),
                    registration_end=_iso(FUTURE - timedelta(days=1)),
                )
            ]
        )

        result = await sync_deadlines(app_container)

        exam_ids = {d.id for d in result}
        assert "exam:E1" in exam_ids
        assert "examreg:E1" in exam_ids

    async def test_skips_assignments_without_due_date(self, app_container: MagicMock) -> None:
        from sophia.services.chronos import sync_deadlines

        app_container.moodle.get_enrolled_courses = AsyncMock(
            return_value=[Course(id=42, fullname="Algorithms", shortname="186.813")]
        )
        app_container.moodle.get_assignments = AsyncMock(
            return_value=[AssignmentInfo(id=1, name="HW1", course_id=42, due_date=None)]
        )
        app_container.moodle.get_checkmarks = AsyncMock(return_value=[])
        app_container.tiss.get_exam_dates = AsyncMock(return_value=[])

        result = await sync_deadlines(app_container)
        assert len(result) == 0

    async def test_continues_on_course_error(self, app_container: MagicMock) -> None:
        """One course failing doesn't break the whole sync."""
        from sophia.services.chronos import sync_deadlines

        app_container.moodle.get_enrolled_courses = AsyncMock(
            return_value=[
                Course(id=42, fullname="Algorithms", shortname="186.813"),
                Course(id=99, fullname="Databases", shortname="184.686"),
            ]
        )

        call_count = 0

        async def assignments_side_effect(course_ids: list[int]) -> list[AssignmentInfo]:
            nonlocal call_count
            call_count += 1
            if 42 in course_ids:
                raise RuntimeError("Moodle down")
            return [AssignmentInfo(id=2, name="DB-HW", course_id=99, due_date=_unix_ts(FUTURE))]

        app_container.moodle.get_assignments = AsyncMock(side_effect=assignments_side_effect)
        app_container.moodle.get_checkmarks = AsyncMock(return_value=[])
        app_container.tiss.get_exam_dates = AsyncMock(return_value=[])

        result = await sync_deadlines(app_container)
        assert len(result) == 1
        assert result[0].course_id == 99

    async def test_upserts_existing_deadline(self, app_container: MagicMock) -> None:
        from sophia.services.chronos import sync_deadlines

        app_container.moodle.get_enrolled_courses = AsyncMock(
            return_value=[Course(id=42, fullname="Algorithms", shortname="186.813")]
        )
        app_container.moodle.get_assignments = AsyncMock(
            return_value=[
                AssignmentInfo(
                    id=1,
                    name="HW1 Updated",
                    course_id=42,
                    due_date=_unix_ts(FUTURE),
                )
            ]
        )
        app_container.moodle.get_checkmarks = AsyncMock(return_value=[])
        app_container.tiss.get_exam_dates = AsyncMock(return_value=[])

        # Insert existing
        await _insert_deadline(app_container.db, id="assign:1", name="HW1")

        result = await sync_deadlines(app_container)
        assert result[0].name == "HW1 Updated"

        cursor = await app_container.db.execute(
            "SELECT COUNT(*) FROM deadline_cache WHERE id = 'assign:1'"
        )
        row = await cursor.fetchone()
        assert row is not None
        count = row[0]
        assert count == 1


# ---------------------------------------------------------------------------
# get_deadlines
# ---------------------------------------------------------------------------


class TestGetDeadlines:
    async def test_returns_future_deadlines(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_deadlines

        await _insert_deadline(db, due_at=_iso(FUTURE))
        await _insert_deadline(db, id="assign:2", name="Past", due_at=_iso(PAST))

        result = await get_deadlines(db)
        assert len(result) == 1
        assert result[0].id == "assign:1"

    async def test_horizon_filtering(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_deadlines

        await _insert_deadline(db, due_at=_iso(FUTURE))  # 5 days
        await _insert_deadline(db, id="assign:far", name="Far", due_at=_iso(FAR_FUTURE))

        result = await get_deadlines(db, horizon_days=7)
        assert len(result) == 1
        assert result[0].id == "assign:1"

    async def test_course_filter(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_deadlines

        await _insert_deadline(db, course_id=42, course_name="Algorithms")
        await _insert_deadline(db, id="assign:2", course_id=99, course_name="Databases")

        result = await get_deadlines(db, course_id=42)
        assert len(result) == 1
        assert result[0].course_id == 42

    async def test_empty_cache(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_deadlines

        result = await get_deadlines(db)
        assert result == []

    async def test_sorted_by_due_date(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_deadlines

        later = FUTURE + timedelta(days=1)
        await _insert_deadline(db, id="assign:2", name="Later", due_at=_iso(later))
        await _insert_deadline(db, id="assign:1", name="Sooner", due_at=_iso(FUTURE))

        result = await get_deadlines(db, horizon_days=14)
        assert result[0].name == "Sooner"
        assert result[1].name == "Later"


# ---------------------------------------------------------------------------
# record_estimate + metacognition_log
# ---------------------------------------------------------------------------


class TestRecordEstimate:
    async def test_stores_estimate(self, app_container: MagicMock) -> None:
        from sophia.services.chronos import record_estimate

        await _insert_deadline(app_container.db)

        est = await record_estimate(
            app_container, deadline_id="assign:1", course_id=42, predicted_hours=5.0
        )

        assert est.predicted_hours == 5.0
        assert est.scaffold_level == EstimationScaffold.FULL

        cursor = await app_container.db.execute(
            "SELECT predicted_hours FROM effort_estimates WHERE deadline_id = 'assign:1'"
        )
        row = await cursor.fetchone()
        assert row[0] == 5.0

    async def test_writes_metacognition_log(self, app_container: MagicMock) -> None:
        from sophia.services.chronos import record_estimate

        await _insert_deadline(app_container.db)

        await record_estimate(
            app_container, deadline_id="assign:1", course_id=42, predicted_hours=3.0
        )

        cursor = await app_container.db.execute(
            "SELECT domain, item_id, predicted FROM metacognition_log"
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "effort:assignment"
        assert row[1] == "assign:1"
        assert row[2] == pytest.approx(3.0)  # pyright: ignore[reportUnknownMemberType]

    async def test_stores_breakdown(self, app_container: MagicMock) -> None:
        from sophia.services.chronos import record_estimate

        await _insert_deadline(app_container.db)
        breakdown = {"reading": 2.0, "coding": 1.0}

        est = await record_estimate(
            app_container,
            deadline_id="assign:1",
            course_id=42,
            predicted_hours=3.0,
            breakdown=breakdown,
        )

        assert est.breakdown == breakdown
        cursor = await app_container.db.execute(
            "SELECT breakdown FROM effort_estimates WHERE deadline_id = 'assign:1'"
        )
        row = await cursor.fetchone()
        assert json.loads(row[0]) == breakdown

    async def test_stores_implementation_intention(self, app_container: MagicMock) -> None:
        from sophia.services.chronos import record_estimate

        await _insert_deadline(app_container.db)

        est = await record_estimate(
            app_container,
            deadline_id="assign:1",
            course_id=42,
            predicted_hours=2.0,
            intention="Monday 2pm at library",
        )

        assert est.implementation_intention == "Monday 2pm at library"


# ---------------------------------------------------------------------------
# get_scaffold_level
# ---------------------------------------------------------------------------


class TestGetScaffoldLevel:
    async def test_full_scaffold_no_history(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_scaffold_level

        level = await get_scaffold_level(db, DeadlineType.ASSIGNMENT, course_id=42)
        assert level == EstimationScaffold.FULL

    async def test_count_fallback_minimal(self, db: aiosqlite.Connection) -> None:
        """10-25 estimates → MINIMAL scaffold."""
        from sophia.services.chronos import get_scaffold_level

        for i in range(15):
            await db.execute(
                "INSERT INTO effort_estimates "
                "(deadline_id, course_id, predicted_hours, scaffold_level) "
                "VALUES (?, ?, ?, ?)",
                (f"assign:{i}", 42, 2.0, "full"),
            )
        await db.commit()

        level = await get_scaffold_level(db, DeadlineType.ASSIGNMENT, course_id=42)
        assert level == EstimationScaffold.MINIMAL

    async def test_count_fallback_open(self, db: aiosqlite.Connection) -> None:
        """Over 25 estimates → OPEN scaffold."""
        from sophia.services.chronos import get_scaffold_level

        for i in range(30):
            await db.execute(
                "INSERT INTO effort_estimates "
                "(deadline_id, course_id, predicted_hours, scaffold_level) "
                "VALUES (?, ?, ?, ?)",
                (f"assign:{i}", 42, 2.0, "full"),
            )
        await db.commit()

        level = await get_scaffold_level(db, DeadlineType.ASSIGNMENT, course_id=42)
        assert level == EstimationScaffold.OPEN

    async def test_calibration_based_high_error(self, db: aiosqlite.Connection) -> None:
        """≥5 metacognition entries with high error → FULL scaffold."""
        from sophia.services.chronos import get_scaffold_level

        for i in range(5):
            await db.execute(
                "INSERT OR REPLACE INTO metacognition_log "
                "(domain, item_id, predicted, actual) VALUES (?, ?, ?, ?)",
                ("effort:assignment", f"assign:{i}", 5.0, 2.0),
            )
        await db.commit()

        level = await get_scaffold_level(db, DeadlineType.ASSIGNMENT, course_id=42)
        assert level == EstimationScaffold.FULL

    async def test_calibration_based_low_error(self, db: aiosqlite.Connection) -> None:
        """≥5 entries with low error → OPEN scaffold."""
        from sophia.services.chronos import get_scaffold_level

        for i in range(5):
            await db.execute(
                "INSERT OR REPLACE INTO metacognition_log "
                "(domain, item_id, predicted, actual) VALUES (?, ?, ?, ?)",
                ("effort:assignment", f"assign:{i}", 3.0, 3.1),
            )
        await db.commit()

        level = await get_scaffold_level(db, DeadlineType.ASSIGNMENT, course_id=42)
        assert level == EstimationScaffold.OPEN

    async def test_calibration_based_medium_error(self, db: aiosqlite.Connection) -> None:
        """≥5 entries with medium error → MINIMAL scaffold."""
        from sophia.services.chronos import get_scaffold_level

        for i in range(5):
            await db.execute(
                "INSERT OR REPLACE INTO metacognition_log "
                "(domain, item_id, predicted, actual) VALUES (?, ?, ?, ?)",
                ("effort:assignment", f"assign:{i}", 3.0, 3.5),
            )
        await db.commit()

        level = await get_scaffold_level(db, DeadlineType.ASSIGNMENT, course_id=42)
        assert level == EstimationScaffold.MINIMAL


# ---------------------------------------------------------------------------
# format_reference_class_hint
# ---------------------------------------------------------------------------


class TestFormatReferenceClassHint:
    async def test_no_hint_when_insufficient_data(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import format_reference_class_hint

        hint = await format_reference_class_hint(db, DeadlineType.ASSIGNMENT)
        assert hint is None

    async def test_hint_with_sufficient_data(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import format_reference_class_hint

        for i in range(3):
            await db.execute(
                "INSERT OR REPLACE INTO metacognition_log "
                "(domain, item_id, predicted, actual) VALUES (?, ?, ?, ?)",
                ("effort:assignment", f"assign:{i}", 3.0, float(2 + i)),
            )
        await db.commit()

        hint = await format_reference_class_hint(db, DeadlineType.ASSIGNMENT)
        assert hint is not None
        assert "hour" in hint.lower()

    async def test_hint_filters_by_course(self, db: aiosqlite.Connection) -> None:
        """When course_id is given but no entries match, return None."""
        from sophia.services.chronos import format_reference_class_hint

        # Insert entries for a different course (item_id encodes course)
        for i in range(5):
            await db.execute(
                "INSERT OR REPLACE INTO metacognition_log "
                "(domain, item_id, predicted, actual) VALUES (?, ?, ?, ?)",
                ("effort:assignment", f"assign:{i}", 3.0, float(2 + i)),
            )
        await db.commit()

        # With no course filter, should have a hint
        hint = await format_reference_class_hint(db, DeadlineType.ASSIGNMENT)
        assert hint is not None


# ---------------------------------------------------------------------------
# get_reference_class
# ---------------------------------------------------------------------------


class TestGetReferenceClass:
    async def test_returns_past_estimates(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_reference_class

        for i in range(3):
            await db.execute(
                "INSERT OR REPLACE INTO metacognition_log "
                "(domain, item_id, predicted, actual) VALUES (?, ?, ?, ?)",
                ("effort:assignment", f"assign:{i}", 3.0, float(2 + i)),
            )
        await db.commit()

        refs = await get_reference_class(db, DeadlineType.ASSIGNMENT)
        assert len(refs) == 3

    async def test_empty_for_unknown_type(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_reference_class

        refs = await get_reference_class(db, DeadlineType.QUIZ)
        assert refs == []


# ---------------------------------------------------------------------------
# Phase 2 — Time Tracking + Post-Deadline Reflection
# ---------------------------------------------------------------------------


class TestStartTimer:
    async def test_starts_timer(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import start_timer

        await start_timer(db, "assign:1")

        cursor = await db.execute(
            "SELECT deadline_id, started_at FROM active_timers WHERE deadline_id = ?",
            ("assign:1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "assign:1"

    async def test_error_if_already_running(self, db: aiosqlite.Connection) -> None:
        from sophia.domain.errors import ChronosError
        from sophia.services.chronos import start_timer

        await start_timer(db, "assign:1")
        with pytest.raises(ChronosError, match="already running"):
            await start_timer(db, "assign:1")


class TestStopTimer:
    async def test_stops_and_records_time(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import start_timer, stop_timer

        await start_timer(db, "assign:1")
        # Backdate the timer start so elapsed > 0
        await db.execute(
            "UPDATE active_timers SET started_at = ? WHERE deadline_id = ?",
            (
                (datetime.now(UTC) - timedelta(hours=1, minutes=30)).isoformat(),
                "assign:1",
            ),
        )
        await db.commit()

        hours = await stop_timer(db, "assign:1")
        assert hours == pytest.approx(1.5, abs=0.05)

        # Timer row should be gone
        cursor = await db.execute(
            "SELECT COUNT(*) FROM active_timers WHERE deadline_id = ?", ("assign:1",)
        )
        row2 = await cursor.fetchone()
        assert row2 is not None
        assert row2[0] == 0

        # Time entry should exist
        cursor = await db.execute(
            "SELECT hours, source FROM time_entries WHERE deadline_id = ?", ("assign:1",)
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == pytest.approx(1.5, abs=0.05)
        assert row[1] == "timer"

    async def test_error_if_not_running(self, db: aiosqlite.Connection) -> None:
        from sophia.domain.errors import ChronosError
        from sophia.services.chronos import stop_timer

        with pytest.raises(ChronosError, match="No timer running"):
            await stop_timer(db, "assign:1")


class TestRecordTime:
    async def test_manual_entry(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import record_time

        await record_time(db, "assign:1", 2.5)

        cursor = await db.execute(
            "SELECT hours, source, note FROM time_entries WHERE deadline_id = ?",
            ("assign:1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == pytest.approx(2.5)
        assert row[1] == "manual"
        assert row[2] is None

    async def test_with_note(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import record_time

        await record_time(db, "assign:1", 1.0, note="Researched the topic")

        cursor = await db.execute(
            "SELECT note FROM time_entries WHERE deadline_id = ?", ("assign:1",)
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "Researched the topic"


class TestGetTrackedTime:
    async def test_sums_all_entries(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_tracked_time, record_time

        await record_time(db, "assign:1", 2.0)
        await record_time(db, "assign:1", 1.5)

        total = await get_tracked_time(db, "assign:1")
        assert total == pytest.approx(3.5)

    async def test_zero_when_no_entries(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_tracked_time

        total = await get_tracked_time(db, "assign:1")
        assert total == 0.0


class TestRecordReflection:
    async def test_stores_reflection(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import record_reflection

        await record_reflection(
            db,
            "assign:1",
            predicted_hours=3.0,
            actual_hours=5.0,
            reflection_text="Underestimated the reading phase.",
        )

        cursor = await db.execute(
            "SELECT deadline_id, predicted_hours, actual_hours, reflection_text "
            "FROM deadline_reflections WHERE deadline_id = ?",
            ("assign:1",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "assign:1"
        assert row[1] == pytest.approx(3.0)
        assert row[2] == pytest.approx(5.0)
        assert row[3] == "Underestimated the reading phase."


class TestCompleteDeadline:
    async def test_updates_metacognition_log(self, app_container: MagicMock) -> None:
        from sophia.services.chronos import complete_deadline, record_time

        db = app_container.db
        await _insert_deadline(db)

        # Record an estimate (creates metacognition_log predicted entry)
        await db.execute(
            "INSERT INTO effort_estimates "
            "(deadline_id, course_id, predicted_hours, scaffold_level) "
            "VALUES (?, ?, ?, ?)",
            ("assign:1", 42, 4.0, "full"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO metacognition_log "
            "(domain, item_id, predicted, predicted_at) VALUES (?, ?, ?, ?)",
            ("effort:assignment", "assign:1", 4.0, datetime.now(UTC).isoformat()),
        )
        await db.commit()

        # Track some time
        await record_time(db, "assign:1", 3.0)
        await record_time(db, "assign:1", 2.0)

        predicted, actual, _ = await complete_deadline(app_container, "assign:1")

        assert predicted == pytest.approx(4.0)
        assert actual == pytest.approx(5.0)

        # metacognition_log should have actual updated
        cursor = await db.execute(
            "SELECT actual FROM metacognition_log WHERE domain = ? AND item_id = ?",
            ("effort:assignment", "assign:1"),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == pytest.approx(5.0)

    async def test_returns_feedback(self, app_container: MagicMock) -> None:
        from sophia.services.chronos import complete_deadline, record_time

        db = app_container.db
        await _insert_deadline(db)

        await db.execute(
            "INSERT INTO effort_estimates "
            "(deadline_id, course_id, predicted_hours, scaffold_level) "
            "VALUES (?, ?, ?, ?)",
            ("assign:1", 42, 4.0, "full"),
        )
        await db.execute(
            "INSERT OR REPLACE INTO metacognition_log "
            "(domain, item_id, predicted, predicted_at) VALUES (?, ?, ?, ?)",
            ("effort:assignment", "assign:1", 4.0, datetime.now(UTC).isoformat()),
        )
        await db.commit()

        await record_time(db, "assign:1", 4.2)

        _, _, feedback = await complete_deadline(app_container, "assign:1")
        assert "✅" in feedback  # well calibrated


class TestFormatEstimationFeedback:
    def test_well_calibrated(self) -> None:
        from sophia.services.chronos import format_estimation_feedback

        result = format_estimation_feedback(4.0, 4.2)
        assert "✅" in result
        assert "4.0" in result
        assert "4.2" in result

    def test_underestimate(self) -> None:
        from sophia.services.chronos import format_estimation_feedback

        result = format_estimation_feedback(3.0, 5.0)
        assert "🔍" in result
        assert "3.0" in result
        assert "5.0" in result

    def test_overestimate(self) -> None:
        from sophia.services.chronos import format_estimation_feedback

        result = format_estimation_feedback(6.0, 3.0)
        assert "💪" in result
        assert "6.0" in result
        assert "3.0" in result

    def test_large_underestimate(self) -> None:
        from sophia.services.chronos import format_estimation_feedback

        result = format_estimation_feedback(3.0, 9.0)
        assert "🔍" in result
        # Should normalize the error, not guilt-frame
        assert "behind" not in result.lower()
        assert "common" in result.lower()


# ---------------------------------------------------------------------------
# Phase 3 — Priority Scoring + Smart Display
# ---------------------------------------------------------------------------


class TestComputePriorityScore:
    def test_basic_priority_score(self) -> None:
        from sophia.services.chronos import compute_priority_score

        deadline = Deadline(
            id="assign:1",
            name="HW1",
            course_id=42,
            course_name="Algorithms",
            deadline_type=DeadlineType.ASSIGNMENT,
            due_at=datetime.now(UTC) + timedelta(hours=48),
            grade_weight=0.3,
        )
        result = compute_priority_score(deadline, estimated_hours=5.0, tracked_hours=2.0)

        assert "urgency" in result
        assert "importance" in result
        assert "effort_gap" in result
        assert "score" in result
        assert result["score"] > 0
        assert result["score"] == pytest.approx(
            result["urgency"] * result["importance"] * result["effort_gap"]
        )

    def test_higher_urgency_closer_deadline(self) -> None:
        from sophia.services.chronos import compute_priority_score

        close = Deadline(
            id="assign:1",
            name="Soon",
            course_id=42,
            course_name="Algo",
            deadline_type=DeadlineType.ASSIGNMENT,
            due_at=datetime.now(UTC) + timedelta(hours=6),
            grade_weight=0.5,
        )
        far = Deadline(
            id="assign:2",
            name="Later",
            course_id=42,
            course_name="Algo",
            deadline_type=DeadlineType.ASSIGNMENT,
            due_at=datetime.now(UTC) + timedelta(hours=72),
            grade_weight=0.5,
        )
        score_close = compute_priority_score(close, estimated_hours=3.0, tracked_hours=0.0)
        score_far = compute_priority_score(far, estimated_hours=3.0, tracked_hours=0.0)

        assert score_close["urgency"] > score_far["urgency"]
        assert score_close["score"] > score_far["score"]

    def test_importance_defaults_when_no_weight(self) -> None:
        from sophia.services.chronos import compute_priority_score

        deadline = Deadline(
            id="assign:1",
            name="HW1",
            course_id=42,
            course_name="Algo",
            deadline_type=DeadlineType.ASSIGNMENT,
            due_at=datetime.now(UTC) + timedelta(days=3),
        )
        result = compute_priority_score(deadline, estimated_hours=4.0, tracked_hours=0.0)

        assert result["importance"] == pytest.approx(0.5)

    def test_effort_gap_with_partial_tracking(self) -> None:
        from sophia.services.chronos import compute_priority_score

        deadline = Deadline(
            id="assign:1",
            name="HW1",
            course_id=42,
            course_name="Algo",
            deadline_type=DeadlineType.ASSIGNMENT,
            due_at=datetime.now(UTC) + timedelta(days=3),
            grade_weight=0.4,
        )
        result = compute_priority_score(deadline, estimated_hours=10.0, tracked_hours=7.0)

        assert result["effort_gap"] == pytest.approx(3.0)

    def test_score_zero_effort_gap_minimum(self) -> None:
        """When tracked >= estimated, effort_gap floors at 0.5."""
        from sophia.services.chronos import compute_priority_score

        deadline = Deadline(
            id="assign:1",
            name="HW1",
            course_id=42,
            course_name="Algo",
            deadline_type=DeadlineType.ASSIGNMENT,
            due_at=datetime.now(UTC) + timedelta(days=3),
            grade_weight=0.4,
        )
        result = compute_priority_score(deadline, estimated_hours=5.0, tracked_hours=6.0)

        assert result["effort_gap"] == pytest.approx(0.5)

    def test_no_estimate_uses_default_effort_gap(self) -> None:
        """When estimated_hours is None, effort_gap should use a sensible default."""
        from sophia.services.chronos import compute_priority_score

        deadline = Deadline(
            id="assign:1",
            name="HW1",
            course_id=42,
            course_name="Algo",
            deadline_type=DeadlineType.ASSIGNMENT,
            due_at=datetime.now(UTC) + timedelta(days=3),
        )
        result = compute_priority_score(deadline, estimated_hours=None, tracked_hours=0.0)

        assert result["effort_gap"] == pytest.approx(0.5)
        assert result["score"] > 0


class TestGetWorkloadForecast:
    async def test_empty_forecast(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_workload_forecast

        result = await get_workload_forecast(db, horizon_days=7)

        assert result["total_estimated_hours"] == pytest.approx(0.0)
        assert result["total_tracked_hours"] == pytest.approx(0.0)
        assert result["remaining_hours"] == pytest.approx(0.0)
        assert result["deadline_count"] == 0

    async def test_forecast_with_estimates(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_workload_forecast, record_time

        due_in_3 = datetime.now(UTC) + timedelta(days=3)
        due_in_5 = datetime.now(UTC) + timedelta(days=5)

        await _insert_deadline(db, id="assign:1", name="HW1", due_at=_iso(due_in_3))
        await _insert_deadline(db, id="assign:2", name="HW2", due_at=_iso(due_in_5))

        # Add estimates
        await db.execute(
            "INSERT INTO effort_estimates "
            "(deadline_id, course_id, predicted_hours, scaffold_level) "
            "VALUES (?, ?, ?, ?)",
            ("assign:1", 42, 4.0, "full"),
        )
        await db.execute(
            "INSERT INTO effort_estimates "
            "(deadline_id, course_id, predicted_hours, scaffold_level) "
            "VALUES (?, ?, ?, ?)",
            ("assign:2", 42, 6.0, "full"),
        )
        await db.commit()

        await record_time(db, "assign:1", 1.5)

        result = await get_workload_forecast(db, horizon_days=7)

        assert result["total_estimated_hours"] == pytest.approx(10.0)
        assert result["total_tracked_hours"] == pytest.approx(1.5)
        assert result["remaining_hours"] == pytest.approx(8.5)
        assert result["deadline_count"] == 2
        assert isinstance(result["per_day"], dict)

    async def test_forecast_only_includes_horizon(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_workload_forecast

        in_range = datetime.now(UTC) + timedelta(days=3)
        out_of_range = datetime.now(UTC) + timedelta(days=20)

        await _insert_deadline(db, id="assign:1", name="Near", due_at=_iso(in_range))
        await _insert_deadline(db, id="assign:2", name="Far", due_at=_iso(out_of_range))

        await db.execute(
            "INSERT INTO effort_estimates "
            "(deadline_id, course_id, predicted_hours, scaffold_level) "
            "VALUES (?, ?, ?, ?)",
            ("assign:1", 42, 3.0, "full"),
        )
        await db.execute(
            "INSERT INTO effort_estimates "
            "(deadline_id, course_id, predicted_hours, scaffold_level) "
            "VALUES (?, ?, ?, ?)",
            ("assign:2", 42, 8.0, "full"),
        )
        await db.commit()

        result = await get_workload_forecast(db, horizon_days=7)

        assert result["deadline_count"] == 1
        assert result["total_estimated_hours"] == pytest.approx(3.0)


class TestSortOrder:
    """Verify that compute_priority_score enables correct sort ordering."""

    def test_sort_by_urgency(self) -> None:
        from sophia.services.chronos import compute_priority_score

        deadlines = [
            Deadline(
                id="assign:1",
                name="Far",
                course_id=42,
                course_name="Algo",
                deadline_type=DeadlineType.ASSIGNMENT,
                due_at=datetime.now(UTC) + timedelta(days=7),
                grade_weight=0.5,
            ),
            Deadline(
                id="assign:2",
                name="Close",
                course_id=42,
                course_name="Algo",
                deadline_type=DeadlineType.ASSIGNMENT,
                due_at=datetime.now(UTC) + timedelta(hours=12),
                grade_weight=0.5,
            ),
            Deadline(
                id="assign:3",
                name="Medium",
                course_id=42,
                course_name="Algo",
                deadline_type=DeadlineType.ASSIGNMENT,
                due_at=datetime.now(UTC) + timedelta(days=3),
                grade_weight=0.5,
            ),
        ]

        scored = sorted(
            deadlines,
            key=lambda d: compute_priority_score(d, 5.0, 0.0)["score"],
            reverse=True,
        )
        assert scored[0].name == "Close"
        assert scored[-1].name == "Far"

    def test_sort_by_weight(self) -> None:
        deadlines = [
            Deadline(
                id="assign:1",
                name="Low",
                course_id=42,
                course_name="Algo",
                deadline_type=DeadlineType.ASSIGNMENT,
                due_at=datetime.now(UTC) + timedelta(days=3),
                grade_weight=0.1,
            ),
            Deadline(
                id="assign:2",
                name="High",
                course_id=42,
                course_name="Algo",
                deadline_type=DeadlineType.ASSIGNMENT,
                due_at=datetime.now(UTC) + timedelta(days=3),
                grade_weight=0.5,
            ),
            Deadline(
                id="assign:3",
                name="None",
                course_id=42,
                course_name="Algo",
                deadline_type=DeadlineType.ASSIGNMENT,
                due_at=datetime.now(UTC) + timedelta(days=3),
            ),
        ]

        sorted_by_weight = sorted(
            deadlines,
            key=lambda d: d.grade_weight or 0,
            reverse=True,
        )
        assert sorted_by_weight[0].name == "High"
        assert sorted_by_weight[-1].name == "None"

    def test_sort_by_effort(self) -> None:
        from sophia.services.chronos import compute_priority_score

        deadlines_with_estimates: list[tuple[Deadline, float, float]] = [
            (
                Deadline(
                    id="assign:1",
                    name="Little Left",
                    course_id=42,
                    course_name="Algo",
                    deadline_type=DeadlineType.ASSIGNMENT,
                    due_at=datetime.now(UTC) + timedelta(days=3),
                ),
                5.0,
                4.0,
            ),
            (
                Deadline(
                    id="assign:2",
                    name="Lots Left",
                    course_id=42,
                    course_name="Algo",
                    deadline_type=DeadlineType.ASSIGNMENT,
                    due_at=datetime.now(UTC) + timedelta(days=3),
                ),
                10.0,
                1.0,
            ),
        ]

        sorted_by_effort = sorted(
            deadlines_with_estimates,
            key=lambda t: compute_priority_score(t[0], t[1], t[2])["effort_gap"],
            reverse=True,
        )
        assert sorted_by_effort[0][0].name == "Lots Left"


# ---------------------------------------------------------------------------
# Phase 4 — Calibration Dashboard + ICS Export + Athena Integration
# ---------------------------------------------------------------------------


async def _insert_metacognition(
    db: aiosqlite.Connection,
    domain: str,
    item_id: str,
    predicted: float,
    actual: float | None = None,
    predicted_at: str | None = None,
) -> None:
    """Helper to insert a metacognition log entry."""
    ts = predicted_at or datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT OR REPLACE INTO metacognition_log "
        "(domain, item_id, predicted, actual, predicted_at, actual_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (domain, item_id, predicted, actual, ts, ts if actual else None),
    )
    await db.commit()


async def _insert_deadline_cache(
    db: aiosqlite.Connection,
    *,
    deadline_id: str = "assign:1",
    name: str = "Test Deadline",
    course_id: int = 42,
    course_name: str = "Algorithms",
    deadline_type: str = "assignment",
    due_at: str | None = None,
    grade_weight: float | None = None,
) -> None:
    """Helper to insert a deadline into the cache."""
    if due_at is None:
        due_at = (datetime.now(UTC) + timedelta(days=5)).isoformat()
    await db.execute(
        "INSERT OR REPLACE INTO deadline_cache "
        "(id, name, course_id, course_name, deadline_type, due_at, "
        "grade_weight, submission_status, url, extra, synced_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            deadline_id,
            name,
            course_id,
            course_name,
            deadline_type,
            due_at,
            grade_weight,
            None,
            None,
            "{}",
            datetime.now(UTC).isoformat(),
        ),
    )
    await db.commit()


class TestCalibrationMetrics:
    async def test_returns_metrics_for_completed_domains(self, db: aiosqlite.Connection) -> None:
        """Insert 3+ completed effort entries → metrics returned."""
        from sophia.services.chronos import get_calibration_metrics

        for i in range(4):
            await _insert_metacognition(db, "effort:assignment", f"a:{i}", 5.0, 6.0)

        metrics = await get_calibration_metrics(db)
        assert len(metrics) == 1
        m = metrics[0]
        assert m.domain == "effort:assignment"
        assert m.sample_count == 4
        assert m.mean_error == pytest.approx(1.0)  # actual - predicted = 6-5=1
        assert m.mean_absolute_error == pytest.approx(1.0)

    async def test_empty_when_insufficient_data(self, db: aiosqlite.Connection) -> None:
        """<3 entries → no metrics."""
        from sophia.services.chronos import get_calibration_metrics

        await _insert_metacognition(db, "effort:assignment", "a:1", 5.0, 6.0)
        await _insert_metacognition(db, "effort:assignment", "a:2", 5.0, 7.0)

        metrics = await get_calibration_metrics(db)
        assert len(metrics) == 0

    async def test_trend_improving(self, db: aiosqlite.Connection) -> None:
        """Recent errors smaller than older → improving."""
        from sophia.services.chronos import get_calibration_metrics

        base = datetime(2026, 1, 1, tzinfo=UTC)
        # Older entries: large error (predicted=5, actual=10 → error=5)
        for i in range(5):
            ts = (base + timedelta(days=i)).isoformat()
            await _insert_metacognition(db, "effort:assignment", f"old:{i}", 5.0, 10.0, ts)
        # Recent entries: small error (predicted=5, actual=5.5 → error=0.5)
        for i in range(5):
            ts = (base + timedelta(days=10 + i)).isoformat()
            await _insert_metacognition(db, "effort:assignment", f"new:{i}", 5.0, 5.5, ts)

        metrics = await get_calibration_metrics(db)
        assert len(metrics) == 1
        assert metrics[0].trend == "improving"

    async def test_trend_declining(self, db: aiosqlite.Connection) -> None:
        """Recent errors larger than older → declining."""
        from sophia.services.chronos import get_calibration_metrics

        base = datetime(2026, 1, 1, tzinfo=UTC)
        # Older: small error
        for i in range(5):
            ts = (base + timedelta(days=i)).isoformat()
            await _insert_metacognition(db, "effort:assignment", f"old:{i}", 5.0, 5.5, ts)
        # Recent: large error
        for i in range(5):
            ts = (base + timedelta(days=10 + i)).isoformat()
            await _insert_metacognition(db, "effort:assignment", f"new:{i}", 5.0, 10.0, ts)

        metrics = await get_calibration_metrics(db)
        assert len(metrics) == 1
        assert metrics[0].trend == "declining"

    async def test_trend_stable(self, db: aiosqlite.Connection) -> None:
        """Similar errors → stable."""
        from sophia.services.chronos import get_calibration_metrics

        base = datetime(2026, 1, 1, tzinfo=UTC)
        for i in range(10):
            ts = (base + timedelta(days=i)).isoformat()
            await _insert_metacognition(db, "effort:assignment", f"e:{i}", 5.0, 6.0, ts)

        metrics = await get_calibration_metrics(db)
        assert len(metrics) == 1
        assert metrics[0].trend == "stable"

    async def test_filters_by_deadline_type(self, db: aiosqlite.Connection) -> None:
        """Only returns metrics for specified type."""
        from sophia.services.chronos import get_calibration_metrics

        for i in range(4):
            await _insert_metacognition(db, "effort:assignment", f"a:{i}", 5.0, 6.0)
            await _insert_metacognition(db, "effort:exam", f"e:{i}", 3.0, 4.0)

        metrics = await get_calibration_metrics(db, deadline_type=DeadlineType.ASSIGNMENT)
        assert len(metrics) == 1
        assert metrics[0].domain == "effort:assignment"


class TestGetUpcomingExams:
    async def test_returns_exam_deadlines(self, db: aiosqlite.Connection) -> None:
        """Insert exam + assignment, only exam returned."""
        from sophia.services.chronos import get_upcoming_exams

        await _insert_deadline_cache(
            db,
            deadline_id="exam:1",
            name="Final Exam",
            deadline_type="exam",
        )
        await _insert_deadline_cache(
            db,
            deadline_id="assign:1",
            name="HW1",
            deadline_type="assignment",
        )

        exams = await get_upcoming_exams(db)
        assert len(exams) == 1
        assert exams[0].name == "Final Exam"
        assert exams[0].deadline_type == DeadlineType.EXAM

    async def test_filters_by_course(self, db: aiosqlite.Connection) -> None:
        """Only returns exams for specified course."""
        from sophia.services.chronos import get_upcoming_exams

        await _insert_deadline_cache(
            db,
            deadline_id="exam:1",
            name="Algo Exam",
            deadline_type="exam",
            course_id=42,
        )
        await _insert_deadline_cache(
            db,
            deadline_id="exam:2",
            name="DB Exam",
            deadline_type="exam",
            course_id=99,
        )

        exams = await get_upcoming_exams(db, course_id=42)
        assert len(exams) == 1
        assert exams[0].name == "Algo Exam"

    async def test_excludes_past_exams(self, db: aiosqlite.Connection) -> None:
        """Past exams not returned."""
        from sophia.services.chronos import get_upcoming_exams

        past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        await _insert_deadline_cache(
            db,
            deadline_id="exam:old",
            name="Past Exam",
            deadline_type="exam",
            due_at=past,
        )
        await _insert_deadline_cache(
            db,
            deadline_id="exam:new",
            name="Future Exam",
            deadline_type="exam",
        )

        exams = await get_upcoming_exams(db)
        assert len(exams) == 1
        assert exams[0].name == "Future Exam"


class TestExportIcs:
    async def test_exports_valid_ics(self, db: aiosqlite.Connection) -> None:
        """Insert deadlines, export ICS, verify parseable by icalendar."""
        from icalendar import Calendar as ICalendar

        from sophia.services.chronos import export_deadlines_ics

        await _insert_deadline_cache(db, deadline_id="a:1", name="HW1")
        await _insert_deadline_cache(db, deadline_id="a:2", name="HW2")

        ics_str = await export_deadlines_ics(db, horizon_days=30)
        cal = ICalendar.from_ical(ics_str)
        events = [c for c in cal.walk() if c.name == "VEVENT"]
        assert len(events) == 2

    async def test_includes_deadline_details(self, db: aiosqlite.Connection) -> None:
        """Verify SUMMARY, DESCRIPTION, UID in exported events."""
        from icalendar import Calendar as ICalendar

        from sophia.services.chronos import export_deadlines_ics

        await _insert_deadline_cache(
            db,
            deadline_id="a:1",
            name="Analysis HW",
            course_name="Math",
            deadline_type="assignment",
        )

        ics_str = await export_deadlines_ics(db, horizon_days=30)
        cal = ICalendar.from_ical(ics_str)
        events = [c for c in cal.walk() if c.name == "VEVENT"]
        assert len(events) == 1
        ev = events[0]
        assert str(ev["SUMMARY"]) == "Analysis HW"
        assert "Math" in str(ev["DESCRIPTION"])
        assert str(ev["UID"]) == "a:1"

    async def test_empty_when_no_deadlines(self, db: aiosqlite.Connection) -> None:
        """No deadlines → valid but empty calendar."""
        from icalendar import Calendar as ICalendar

        from sophia.services.chronos import export_deadlines_ics

        ics_str = await export_deadlines_ics(db, horizon_days=30)
        cal = ICalendar.from_ical(ics_str)
        events = [c for c in cal.walk() if c.name == "VEVENT"]
        assert len(events) == 0


class TestComputePriorityScoreConfidence:
    """Tests for the confidence_multiplier extension."""

    def test_confidence_multiplier_default_is_1(self) -> None:
        from sophia.services.chronos import compute_priority_score

        deadline = Deadline(
            id="assign:1",
            name="HW1",
            course_id=42,
            course_name="Algo",
            deadline_type=DeadlineType.ASSIGNMENT,
            due_at=datetime.now(UTC) + timedelta(hours=48),
            grade_weight=0.3,
        )
        result = compute_priority_score(deadline, estimated_hours=5.0, tracked_hours=2.0)
        assert result["confidence_multiplier"] == pytest.approx(1.0)

    def test_confidence_multiplier_increases_score(self) -> None:
        from sophia.services.chronos import compute_priority_score

        deadline = Deadline(
            id="assign:1",
            name="HW1",
            course_id=42,
            course_name="Algo",
            deadline_type=DeadlineType.ASSIGNMENT,
            due_at=datetime.now(UTC) + timedelta(hours=48),
            grade_weight=0.3,
        )
        base = compute_priority_score(deadline, 5.0, 2.0, confidence_multiplier=1.0)
        boosted = compute_priority_score(deadline, 5.0, 2.0, confidence_multiplier=1.5)
        assert boosted["score"] > base["score"]
        assert boosted["score"] == pytest.approx(base["score"] * 1.5)

    def test_confidence_multiplier_in_result_dict(self) -> None:
        from sophia.services.chronos import compute_priority_score

        deadline = Deadline(
            id="assign:1",
            name="HW1",
            course_id=42,
            course_name="Algo",
            deadline_type=DeadlineType.ASSIGNMENT,
            due_at=datetime.now(UTC) + timedelta(hours=48),
            grade_weight=0.3,
        )
        result = compute_priority_score(deadline, 5.0, 2.0, confidence_multiplier=1.3)
        assert "confidence_multiplier" in result
        assert result["confidence_multiplier"] == pytest.approx(1.3)


class TestGetMissedDeadlines:
    @pytest.mark.asyncio
    async def test_returns_past_due_deadlines(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_missed_deadlines

        past = datetime.now(UTC) - timedelta(days=3)
        await db.execute(
            "INSERT INTO deadline_cache "
            "(id, name, course_id, course_name, deadline_type, due_at) "
            "VALUES ('a:1', 'Old HW', 42, 'Algo', 'assignment', ?)",
            (past.isoformat(),),
        )
        await db.commit()

        result = await get_missed_deadlines(db)
        assert len(result) == 1
        assert result[0].name == "Old HW"

    @pytest.mark.asyncio
    async def test_filters_by_course(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_missed_deadlines

        past = datetime.now(UTC) - timedelta(days=3)
        await db.execute(
            "INSERT INTO deadline_cache "
            "(id, name, course_id, course_name, deadline_type, due_at) "
            "VALUES ('a:1', 'HW1', 42, 'Algo', 'assignment', ?)",
            (past.isoformat(),),
        )
        await db.execute(
            "INSERT INTO deadline_cache "
            "(id, name, course_id, course_name, deadline_type, due_at) "
            "VALUES ('a:2', 'HW2', 99, 'DB', 'assignment', ?)",
            (past.isoformat(),),
        )
        await db.commit()

        result = await get_missed_deadlines(db, course_id=42)
        assert len(result) == 1
        assert result[0].course_id == 42

    @pytest.mark.asyncio
    async def test_respects_limit(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_missed_deadlines

        for i in range(5):
            past = datetime.now(UTC) - timedelta(days=i + 1)
            await db.execute(
                "INSERT INTO deadline_cache "
                "(id, name, course_id, course_name, deadline_type, due_at) "
                "VALUES (?, ?, 42, 'Algo', 'assignment', ?)",
                (f"a:{i}", f"HW{i}", past.isoformat()),
            )
        await db.commit()

        result = await get_missed_deadlines(db, limit=3)
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_when_none_missed(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_missed_deadlines

        future = datetime.now(UTC) + timedelta(days=5)
        await db.execute(
            "INSERT INTO deadline_cache "
            "(id, name, course_id, course_name, deadline_type, due_at) "
            "VALUES ('a:1', 'Future HW', 42, 'Algo', 'assignment', ?)",
            (future.isoformat(),),
        )
        await db.commit()

        result = await get_missed_deadlines(db)
        assert result == []

    @pytest.mark.asyncio
    async def test_most_recent_first(self, db: aiosqlite.Connection) -> None:
        from sophia.services.chronos import get_missed_deadlines

        for i in range(3):
            past = datetime.now(UTC) - timedelta(days=(i + 1) * 2)
            await db.execute(
                "INSERT INTO deadline_cache "
                "(id, name, course_id, course_name, deadline_type, due_at) "
                "VALUES (?, ?, 42, 'Algo', 'assignment', ?)",
                (f"a:{i}", f"HW{i}", past.isoformat()),
            )
        await db.commit()

        result = await get_missed_deadlines(db)
        # Most recent (least days ago) should be first
        assert result[0].name == "HW0"
