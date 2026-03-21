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

        async def assignments_side_effect(course_ids: list[int]) -> list:
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
        count = (await cursor.fetchone())[0]
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
