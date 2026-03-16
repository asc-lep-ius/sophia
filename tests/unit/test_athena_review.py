"""Tests for Athena spaced review scheduling service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from sophia.infra.persistence import run_migrations


@pytest.fixture
async def db():
    db_conn = await aiosqlite.connect(":memory:")
    await db_conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(db_conn)
    yield db_conn
    await db_conn.close()


class TestComputeNextInterval:
    """Unit tests for the pure compute_next_interval function."""

    def test_high_score_advances(self) -> None:
        from sophia.services.athena_review import compute_next_interval

        assert compute_next_interval(0, 0.9) == 1

    def test_medium_score_repeats(self) -> None:
        from sophia.services.athena_review import compute_next_interval

        assert compute_next_interval(2, 0.6) == 2

    def test_low_score_resets(self) -> None:
        from sophia.services.athena_review import compute_next_interval

        assert compute_next_interval(3, 0.3) == 0

    def test_boundary_08_advances(self) -> None:
        from sophia.services.athena_review import compute_next_interval

        assert compute_next_interval(1, 0.8) == 2

    def test_boundary_05_repeats(self) -> None:
        from sophia.services.athena_review import compute_next_interval

        assert compute_next_interval(1, 0.5) == 1

    def test_boundary_below_05_resets(self) -> None:
        from sophia.services.athena_review import compute_next_interval

        assert compute_next_interval(2, 0.49) == 0

    def test_caps_at_max_interval(self) -> None:
        from sophia.services.athena_review import compute_next_interval

        assert compute_next_interval(4, 0.9) == 4


class TestScheduleReview:
    """schedule_review creates or resets a review schedule."""

    @pytest.mark.asyncio
    async def test_creates_schedule(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import schedule_review

        result = await schedule_review(db, "Sorting", course_id=42)

        assert result.topic == "Sorting"
        assert result.course_id == 42
        assert result.interval_index == 0
        assert result.last_reviewed_at is None
        # next_review_at should be ~1 day from now
        next_dt = datetime.fromisoformat(result.next_review_at)
        expected = datetime.now(UTC) + timedelta(days=1)
        assert abs((next_dt - expected).total_seconds()) < 5

    @pytest.mark.asyncio
    async def test_idempotent_resets(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import complete_review, schedule_review

        await schedule_review(db, "Sorting", course_id=42)
        # Advance the schedule
        await complete_review(db, "Sorting", course_id=42, score=0.9)
        # Re-schedule should reset
        reset = await schedule_review(db, "Sorting", course_id=42)

        assert reset.interval_index == 0
        assert reset.last_reviewed_at is None


class TestCompleteReview:
    """complete_review records results and adjusts interval."""

    @pytest.mark.asyncio
    async def test_advances_on_high_score(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import complete_review, schedule_review

        await schedule_review(db, "Sorting", course_id=42)
        result = await complete_review(db, "Sorting", course_id=42, score=0.9)

        assert result.interval_index == 1
        assert result.score_at_last_review == pytest.approx(0.9)
        assert result.last_reviewed_at is not None

    @pytest.mark.asyncio
    async def test_repeats_on_medium_score(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import complete_review, schedule_review

        await schedule_review(db, "Sorting", course_id=42)
        result = await complete_review(db, "Sorting", course_id=42, score=0.6)

        assert result.interval_index == 0

    @pytest.mark.asyncio
    async def test_resets_on_low_score(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import complete_review, schedule_review

        await schedule_review(db, "Sorting", course_id=42)
        # Advance first
        await complete_review(db, "Sorting", course_id=42, score=0.9)
        # Now reset
        result = await complete_review(db, "Sorting", course_id=42, score=0.3)

        assert result.interval_index == 0

    @pytest.mark.asyncio
    async def test_caps_at_max_interval(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import complete_review, schedule_review

        await schedule_review(db, "Sorting", course_id=42)
        # Advance through all intervals: 0→1→2→3→4
        for _ in range(5):
            result = await complete_review(db, "Sorting", course_id=42, score=0.9)

        assert result.interval_index == 4


class TestGetDueReviews:
    """get_due_reviews returns overdue topics."""

    @pytest.mark.asyncio
    async def test_returns_overdue(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import get_due_reviews

        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await db.execute(
            "INSERT INTO review_schedule (topic, course_id, interval_index, next_review_at) "
            "VALUES (?, ?, 0, ?)",
            ("Sorting", 42, past),
        )
        await db.commit()

        due = await get_due_reviews(db)
        assert len(due) == 1
        assert due[0].topic == "Sorting"

    @pytest.mark.asyncio
    async def test_excludes_future(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import get_due_reviews

        future = (datetime.now(UTC) + timedelta(days=5)).isoformat()
        await db.execute(
            "INSERT INTO review_schedule (topic, course_id, interval_index, next_review_at) "
            "VALUES (?, ?, 0, ?)",
            ("Hashing", 42, future),
        )
        await db.commit()

        due = await get_due_reviews(db)
        assert len(due) == 0

    @pytest.mark.asyncio
    async def test_filters_by_course(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import get_due_reviews

        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await db.execute(
            "INSERT INTO review_schedule (topic, course_id, interval_index, next_review_at) "
            "VALUES (?, ?, 0, ?)",
            ("Sorting", 42, past),
        )
        await db.execute(
            "INSERT INTO review_schedule (topic, course_id, interval_index, next_review_at) "
            "VALUES (?, ?, 0, ?)",
            ("Hashing", 99, past),
        )
        await db.commit()

        due = await get_due_reviews(db, course_id=42)
        assert len(due) == 1
        assert due[0].topic == "Sorting"


class TestGetUpcomingReviews:
    """get_upcoming_reviews returns reviews due within N days (not yet due)."""

    @pytest.mark.asyncio
    async def test_returns_upcoming(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import get_upcoming_reviews

        upcoming = (datetime.now(UTC) + timedelta(days=2)).isoformat()
        await db.execute(
            "INSERT INTO review_schedule (topic, course_id, interval_index, next_review_at) "
            "VALUES (?, ?, 0, ?)",
            ("Sorting", 42, upcoming),
        )
        await db.commit()

        results = await get_upcoming_reviews(db, days_ahead=3)
        assert len(results) == 1
        assert results[0].topic == "Sorting"

    @pytest.mark.asyncio
    async def test_excludes_beyond_window(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import get_upcoming_reviews

        far_future = (datetime.now(UTC) + timedelta(days=10)).isoformat()
        await db.execute(
            "INSERT INTO review_schedule (topic, course_id, interval_index, next_review_at) "
            "VALUES (?, ?, 0, ?)",
            ("Sorting", 42, far_future),
        )
        await db.commit()

        results = await get_upcoming_reviews(db, days_ahead=3)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_excludes_already_due(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import get_upcoming_reviews

        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await db.execute(
            "INSERT INTO review_schedule (topic, course_id, interval_index, next_review_at) "
            "VALUES (?, ?, 0, ?)",
            ("Sorting", 42, past),
        )
        await db.commit()

        results = await get_upcoming_reviews(db)
        assert len(results) == 0


class TestGetAllSchedules:
    """get_all_schedules returns all schedules for a course, sorted."""

    @pytest.mark.asyncio
    async def test_returns_sorted(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import get_all_schedules

        now = datetime.now(UTC)
        for i, topic in enumerate(["Hashing", "Sorting", "Graphs"]):
            t = (now + timedelta(days=i)).isoformat()
            await db.execute(
                "INSERT INTO review_schedule (topic, course_id, interval_index, next_review_at) "
                "VALUES (?, ?, 0, ?)",
                (topic, 42, t),
            )
        await db.commit()

        results = await get_all_schedules(db, course_id=42)
        assert len(results) == 3
        assert results[0].topic == "Hashing"
        assert results[1].topic == "Sorting"
        assert results[2].topic == "Graphs"
