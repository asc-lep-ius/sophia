"""Tests for FSRS-inspired adaptive spaced repetition."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from sophia.domain.models import REVIEW_INTERVALS
from sophia.services.athena_review import compute_fsrs_interval

# ---------------------------------------------------------------------------
# Pure algorithm tests
# ---------------------------------------------------------------------------


class TestFSRSPerfectScore:
    def test_increases_stability(self) -> None:
        _, new_stab, _ = compute_fsrs_interval(
            difficulty=0.3, stability=1.0, score=1.0
        )
        assert new_stab > 1.0

    def test_decreases_difficulty(self) -> None:
        new_diff, _, _ = compute_fsrs_interval(
            difficulty=0.5, stability=1.0, score=1.0
        )
        assert new_diff < 0.5


class TestFSRSZeroScore:
    def test_resets_stability(self) -> None:
        _, new_stab, _ = compute_fsrs_interval(
            difficulty=0.3, stability=10.0, score=0.0
        )
        assert new_stab < 10.0

    def test_increases_difficulty(self) -> None:
        new_diff, _, _ = compute_fsrs_interval(
            difficulty=0.3, stability=1.0, score=0.0
        )
        assert new_diff > 0.3


class TestFSRSMediumScore:
    def test_moderate_growth(self) -> None:
        _, new_stab, _ = compute_fsrs_interval(
            difficulty=0.3, stability=3.0, score=0.6
        )
        assert new_stab > 3.0  # still grows
        # but grows less than a perfect score would
        _, perfect_stab, _ = compute_fsrs_interval(
            difficulty=0.3, stability=3.0, score=1.0
        )
        assert new_stab < perfect_stab


class TestFSRSDifficultyClamping:
    def test_clamped_min(self) -> None:
        """Difficulty never drops below 0.1 even with repeated successes."""
        diff = 0.15
        for _ in range(20):
            diff, _, _ = compute_fsrs_interval(
                difficulty=diff, stability=1.0, score=1.0
            )
        assert diff >= 0.1

    def test_clamped_max(self) -> None:
        """Difficulty never exceeds 1.0 even with repeated failures."""
        diff = 0.9
        for _ in range(20):
            diff, _, _ = compute_fsrs_interval(
                difficulty=diff, stability=1.0, score=0.0
            )
        assert diff <= 1.0


class TestFSRSIntervalConstraints:
    def test_interval_minimum_one_day(self) -> None:
        _, _, interval = compute_fsrs_interval(
            difficulty=0.9, stability=0.5, score=0.0
        )
        assert interval >= 1

    def test_stability_minimum_half(self) -> None:
        _, new_stab, _ = compute_fsrs_interval(
            difficulty=0.9, stability=0.5, score=0.0
        )
        assert new_stab >= 0.5


class TestFSRSDifficultyOnFailure:
    def test_difficulty_increases_on_failure(self) -> None:
        new_diff, _, _ = compute_fsrs_interval(
            difficulty=0.3, stability=5.0, score=0.2
        )
        assert new_diff > 0.3


class TestBackwardCompat:
    def test_review_intervals_still_exists(self) -> None:
        assert REVIEW_INTERVALS == [1, 3, 7, 14, 30]


# ---------------------------------------------------------------------------
# Integration tests with in-memory DB
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    from sophia.infra.persistence import run_migrations

    db_conn = await aiosqlite.connect(":memory:")
    await db_conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(db_conn)
    yield db_conn
    await db_conn.close()


class TestCompleteReviewUsesFSRS:
    @pytest.mark.asyncio
    async def test_complete_review_returns_fsrs_fields(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import complete_review, schedule_review

        await schedule_review(db, "Sorting", course_id=42)
        result = await complete_review(db, "Sorting", course_id=42, score=0.9)

        assert result.difficulty is not None
        assert result.stability is not None
        assert result.review_count is not None
        assert result.review_count >= 1

    @pytest.mark.asyncio
    async def test_complete_review_persists_fsrs_columns(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import complete_review, schedule_review

        await schedule_review(db, "Sorting", course_id=42)
        await complete_review(db, "Sorting", course_id=42, score=0.9)

        cursor = await db.execute(
            "SELECT difficulty, stability, review_count "
            "FROM review_schedule WHERE topic = ? AND course_id = ?",
            ("Sorting", 42),
        )
        row = await cursor.fetchone()
        assert row is not None
        difficulty, stability, review_count = row
        assert difficulty is not None
        assert stability is not None
        assert review_count == 1


class TestCompleteReviewHandlesNullColumns:
    @pytest.mark.asyncio
    async def test_null_defaults(self, db: aiosqlite.Connection) -> None:
        """Pre-migration rows with NULL FSRS columns use safe defaults."""
        # Insert a row as if it were created before the FSRS migration
        now = datetime.now(UTC)
        next_at = (now + timedelta(days=1)).isoformat()
        await db.execute(
            "INSERT INTO review_schedule "
            "(topic, course_id, interval_index, next_review_at, "
            "difficulty, stability, review_count) "
            "VALUES (?, ?, 0, ?, NULL, NULL, NULL)",
            ("OldTopic", 42, next_at),
        )
        await db.commit()

        from sophia.services.athena_review import complete_review

        result = await complete_review(db, "OldTopic", course_id=42, score=0.8)

        # Should use safe defaults and not crash
        assert result.difficulty is not None
        assert result.stability is not None
        assert result.review_count >= 1


class TestScheduleReviewInitializesFSRS:
    @pytest.mark.asyncio
    async def test_new_schedule_has_defaults(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_review import schedule_review

        result = await schedule_review(db, "NewTopic", course_id=42)

        assert result.difficulty == pytest.approx(0.3)
        assert result.stability == pytest.approx(1.0)
        assert result.review_count == 0
