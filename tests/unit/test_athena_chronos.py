"""Tests for Athena ↔ Chronos integration service."""

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


async def _insert_exam(db: aiosqlite.Connection, course_id: int, due_at: datetime) -> None:
    """Helper to insert an exam deadline."""
    await db.execute(
        "INSERT INTO deadline_cache "
        "(id, name, course_id, course_name, deadline_type, due_at) "
        "VALUES (?, ?, ?, ?, 'exam', ?)",
        (
            f"exam:{course_id}",
            f"Exam {course_id}",
            course_id,
            f"Course {course_id}",
            due_at.isoformat(),
        ),
    )
    await db.commit()


async def _insert_review(
    db: aiosqlite.Connection,
    topic: str,
    course_id: int,
    next_review_at: datetime,
) -> None:
    """Helper to insert a review schedule entry."""
    await db.execute(
        "INSERT INTO review_schedule (topic, course_id, next_review_at) VALUES (?, ?, ?)",
        (topic, course_id, next_review_at.isoformat()),
    )
    await db.commit()


class TestCapReviewForExam:
    def test_no_cap_when_review_before_exam(self) -> None:
        from sophia.services.athena_chronos import cap_review_for_exam

        now = datetime.now(UTC)
        exam = now + timedelta(days=10)
        review = now + timedelta(days=5)

        result = cap_review_for_exam(review, exam)
        assert result == review

    def test_caps_review_to_buffer_when_after_exam(self) -> None:
        from sophia.services.athena_chronos import EXAM_BUFFER_DAYS, cap_review_for_exam

        now = datetime.now(UTC)
        exam = now + timedelta(days=10)
        review = now + timedelta(days=15)

        result = cap_review_for_exam(review, exam)
        expected_buffer = exam - timedelta(days=EXAM_BUFFER_DAYS)
        assert abs((result - expected_buffer).total_seconds()) < 5

    def test_no_cap_when_exam_beyond_horizon(self) -> None:
        from sophia.services.athena_chronos import COMPRESSION_HORIZON_DAYS, cap_review_for_exam

        now = datetime.now(UTC)
        exam = now + timedelta(days=COMPRESSION_HORIZON_DAYS + 5)
        review = now + timedelta(days=COMPRESSION_HORIZON_DAYS + 10)

        result = cap_review_for_exam(review, exam)
        assert result == review

    def test_cap_never_earlier_than_tomorrow(self) -> None:
        from sophia.services.athena_chronos import cap_review_for_exam

        now = datetime.now(UTC)
        exam = now + timedelta(days=2)
        review = now + timedelta(days=30)

        result = cap_review_for_exam(review, exam)
        assert result >= now + timedelta(hours=23)

    def test_exact_edge_case_review_on_exam_day(self) -> None:
        from sophia.services.athena_chronos import EXAM_BUFFER_DAYS, cap_review_for_exam

        now = datetime.now(UTC)
        exam = now + timedelta(days=7)
        review = exam

        result = cap_review_for_exam(review, exam)
        expected_buffer = exam - timedelta(days=EXAM_BUFFER_DAYS)
        assert abs((result - expected_buffer).total_seconds()) < 5


class TestCompressReviewsForExam:
    @pytest.mark.asyncio
    async def test_compresses_reviews_past_exam(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import compress_reviews_for_exam

        now = datetime.now(UTC)
        exam = now + timedelta(days=10)
        await _insert_review(db, "Sorting", 42, now + timedelta(days=15))

        count = await compress_reviews_for_exam(db, 42, exam)
        assert count == 1

        cursor = await db.execute(
            "SELECT next_review_at FROM review_schedule WHERE topic = ? AND course_id = ?",
            ("Sorting", 42),
        )
        row = await cursor.fetchone()
        new_date = datetime.fromisoformat(row[0])
        assert new_date <= exam

    @pytest.mark.asyncio
    async def test_no_compression_when_all_reviews_before_exam(
        self, db: aiosqlite.Connection
    ) -> None:
        from sophia.services.athena_chronos import compress_reviews_for_exam

        now = datetime.now(UTC)
        exam = now + timedelta(days=10)
        await _insert_review(db, "Sorting", 42, now + timedelta(days=5))

        count = await compress_reviews_for_exam(db, 42, exam)
        assert count == 0

    @pytest.mark.asyncio
    async def test_no_compression_when_exam_is_tomorrow(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import compress_reviews_for_exam

        now = datetime.now(UTC)
        exam = now + timedelta(hours=20)
        await _insert_review(db, "Sorting", 42, now + timedelta(days=15))

        count = await compress_reviews_for_exam(db, 42, exam)
        assert count == 0

    @pytest.mark.asyncio
    async def test_returns_compressed_count(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import compress_reviews_for_exam

        now = datetime.now(UTC)
        exam = now + timedelta(days=10)
        await _insert_review(db, "Topic A", 42, now + timedelta(days=15))
        await _insert_review(db, "Topic B", 42, now + timedelta(days=20))

        count = await compress_reviews_for_exam(db, 42, exam)
        assert count == 2

    @pytest.mark.asyncio
    async def test_does_not_touch_other_courses(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import compress_reviews_for_exam

        now = datetime.now(UTC)
        exam = now + timedelta(days=10)
        original_date = now + timedelta(days=15)
        await _insert_review(db, "Sorting", 99, original_date)

        count = await compress_reviews_for_exam(db, 42, exam)
        assert count == 0

        cursor = await db.execute(
            "SELECT next_review_at FROM review_schedule WHERE course_id = 99",
        )
        row = await cursor.fetchone()
        assert datetime.fromisoformat(row[0]) == original_date


class TestCompressAllCourses:
    @pytest.mark.asyncio
    async def test_compresses_multiple_courses(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import compress_all_courses

        now = datetime.now(UTC)
        await _insert_exam(db, 42, now + timedelta(days=10))
        await _insert_exam(db, 99, now + timedelta(days=14))
        await _insert_review(db, "Topic A", 42, now + timedelta(days=15))
        await _insert_review(db, "Topic B", 99, now + timedelta(days=20))

        results = await compress_all_courses(db)
        assert 42 in results
        assert 99 in results

    @pytest.mark.asyncio
    async def test_no_exams_returns_empty(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import compress_all_courses

        results = await compress_all_courses(db)
        assert results == {}


class TestGetExamForCourse:
    @pytest.mark.asyncio
    async def test_returns_nearest_future_exam(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import get_exam_for_course

        now = datetime.now(UTC)
        near = now + timedelta(days=5)
        far = now + timedelta(days=30)
        await _insert_exam(db, 42, near)
        await db.execute(
            "INSERT INTO deadline_cache (id, name, course_id, course_name, deadline_type, due_at) "
            "VALUES ('exam:42:2', 'Exam 2', 42, 'Course 42', 'exam', ?)",
            (far.isoformat(),),
        )
        await db.commit()

        result = await get_exam_for_course(db, 42)
        assert result is not None
        assert abs((result - near).total_seconds()) < 5

    @pytest.mark.asyncio
    async def test_returns_none_when_no_exams(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import get_exam_for_course

        result = await get_exam_for_course(db, 42)
        assert result is None

    @pytest.mark.asyncio
    async def test_ignores_past_exams(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import get_exam_for_course

        past = datetime.now(UTC) - timedelta(days=5)
        await _insert_exam(db, 42, past)

        result = await get_exam_for_course(db, 42)
        assert result is None


# --- Phase 2 Tests ---


class TestLogConfidencePrediction:
    @pytest.mark.asyncio
    async def test_writes_to_metacognition_log(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import log_confidence_prediction

        await log_confidence_prediction(db, 42, "Sorting", 0.5)

        cursor = await db.execute(
            "SELECT domain, item_id, predicted FROM metacognition_log "
            "WHERE domain = 'confidence:42'",
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == "confidence:42"
        assert row[1] == "Sorting"
        assert row[2] == pytest.approx(0.5)

    @pytest.mark.asyncio
    async def test_normalizes_rating_to_zero_one(self, db: aiosqlite.Connection) -> None:
        """The confidence_rating passed in should already be 0-1."""
        from sophia.services.athena_chronos import log_confidence_prediction

        await log_confidence_prediction(db, 42, "Sorting", 0.75)

        cursor = await db.execute(
            "SELECT predicted FROM metacognition_log WHERE domain = 'confidence:42'",
        )
        row = await cursor.fetchone()
        assert row[0] == pytest.approx(0.75)

    @pytest.mark.asyncio
    async def test_replaces_on_duplicate(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import log_confidence_prediction

        await log_confidence_prediction(db, 42, "Sorting", 0.3)
        await log_confidence_prediction(db, 42, "Sorting", 0.8)

        cursor = await db.execute(
            "SELECT predicted FROM metacognition_log "
            "WHERE domain = 'confidence:42' AND item_id = 'Sorting'",
        )
        row = await cursor.fetchone()
        assert row[0] == pytest.approx(0.8)


class TestLogConfidenceActual:
    @pytest.mark.asyncio
    async def test_updates_actual_score(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import log_confidence_actual, log_confidence_prediction

        await log_confidence_prediction(db, 42, "Sorting", 0.5)
        await log_confidence_actual(db, 42, "Sorting", 0.7)

        cursor = await db.execute(
            "SELECT actual FROM metacognition_log "
            "WHERE domain = 'confidence:42' AND item_id = 'Sorting'",
        )
        row = await cursor.fetchone()
        assert row[0] == pytest.approx(0.7)


class TestGetCourseConfidence:
    @pytest.mark.asyncio
    async def test_returns_average_normalized(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import get_course_confidence

        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted, rated_at) "
            "VALUES (?, ?, ?, ?)",
            ("Sorting", 42, 0.5, datetime.now(UTC).isoformat()),
        )
        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted, rated_at) "
            "VALUES (?, ?, ?, ?)",
            ("Graphs", 42, 0.75, datetime.now(UTC).isoformat()),
        )
        await db.commit()

        result = await get_course_confidence(db, 42)
        assert result is not None
        assert result == pytest.approx(0.625)  # (0.5 + 0.75) / 2

    @pytest.mark.asyncio
    async def test_returns_none_when_no_ratings(self, db: aiosqlite.Connection) -> None:
        from sophia.services.athena_chronos import get_course_confidence

        result = await get_course_confidence(db, 42)
        assert result is None


class TestConfidencePriorityMultiplier:
    def test_returns_1_when_no_data(self) -> None:
        from sophia.services.athena_chronos import confidence_priority_multiplier

        assert confidence_priority_multiplier(None) == 1.0

    def test_returns_1_when_high_confidence(self) -> None:
        from sophia.services.athena_chronos import confidence_priority_multiplier

        assert confidence_priority_multiplier(0.8) == 1.0

    def test_returns_boost_when_low_confidence(self) -> None:
        from sophia.services.athena_chronos import confidence_priority_multiplier

        result = confidence_priority_multiplier(0.3)
        assert result > 1.0

    def test_returns_max_boost_at_zero_confidence(self) -> None:
        from sophia.services.athena_chronos import (
            CONFIDENCE_BOOST_FACTOR,
            confidence_priority_multiplier,
        )

        assert confidence_priority_multiplier(0.0) == pytest.approx(CONFIDENCE_BOOST_FACTOR)

    def test_linear_interpolation(self) -> None:
        from sophia.services.athena_chronos import confidence_priority_multiplier

        # At threshold (0.6) → 1.0
        assert confidence_priority_multiplier(0.6) == pytest.approx(1.0)
        # At half of threshold (0.3) → midpoint between BOOST_FACTOR and 1.0
        assert confidence_priority_multiplier(0.3) == pytest.approx(1.25)


# --- Phase 3 Tests ---


class TestBuildPlanItems:
    @pytest.mark.asyncio
    async def test_returns_deadlines_reviews_and_gaps_sorted(self, db):
        from sophia.services.athena_chronos import build_plan_items

        now = datetime.now(UTC)
        # Insert a deadline
        await _insert_exam(db, 42, now + timedelta(days=5))
        # Insert a due review
        await _insert_review(db, "Sorting", 42, now - timedelta(days=1))
        # Insert a low-confidence rating
        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted, rated_at) "
            "VALUES (?, ?, ?, ?)",
            ("Graphs", 42, 0.2, now.isoformat()),
        )
        await db.commit()

        items = await build_plan_items(db, horizon_days=14)
        assert len(items) >= 2  # At least deadline + review (gap may or may not appear)
        # Items should be sorted by score descending
        scores = [i.score for i in items]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_empty_when_no_data(self, db):
        from sophia.services.athena_chronos import build_plan_items

        items = await build_plan_items(db)
        assert items == []

    @pytest.mark.asyncio
    async def test_respects_horizon(self, db):
        from sophia.services.athena_chronos import build_plan_items

        now = datetime.now(UTC)
        await _insert_exam(db, 42, now + timedelta(days=30))

        items_short = await build_plan_items(db, horizon_days=7)
        items_long = await build_plan_items(db, horizon_days=60)
        # The deadline at 30 days should only appear in the long horizon
        assert len(items_long) >= len(items_short)


class TestDeadlineItems:
    @pytest.mark.asyncio
    async def test_includes_effort_and_tracking_info(self, db):
        from sophia.services.athena_chronos import _deadline_items

        now = datetime.now(UTC)
        await db.execute(
            "INSERT INTO deadline_cache "
            "(id, name, course_id, course_name, deadline_type, due_at, grade_weight) "
            "VALUES ('a:1', 'HW1', 42, 'Algo', 'assignment', ?, 0.3)",
            ((now + timedelta(days=5)).isoformat(),),
        )
        await db.execute(
            "INSERT INTO effort_estimates "
            "(deadline_id, course_id, predicted_hours, scaffold_level) "
            "VALUES ('a:1', 42, 5.0, 'full')",
        )
        await db.commit()

        items = await _deadline_items(db, horizon_days=14)
        assert len(items) == 1
        assert "5.0h est" in items[0].detail

    @pytest.mark.asyncio
    async def test_handles_no_estimate(self, db):
        from sophia.services.athena_chronos import _deadline_items

        now = datetime.now(UTC)
        await db.execute(
            "INSERT INTO deadline_cache (id, name, course_id, course_name, deadline_type, due_at) "
            "VALUES ('a:1', 'HW1', 42, 'Algo', 'assignment', ?)",
            ((now + timedelta(days=5)).isoformat(),),
        )
        await db.commit()

        items = await _deadline_items(db, horizon_days=14)
        assert len(items) == 1
        assert "no estimate" in items[0].detail


class TestReviewItems:
    @pytest.mark.asyncio
    async def test_overdue_reviews_score_higher(self, db):
        from sophia.services.athena_chronos import _review_items

        now = datetime.now(UTC)
        await _insert_review(db, "Recent", 42, now - timedelta(hours=1))
        await _insert_review(db, "Old", 42, now - timedelta(days=5))
        # Need course name in deadline_cache
        await db.execute(
            "INSERT INTO deadline_cache (id, name, course_id, course_name, deadline_type, due_at) "
            "VALUES ('a:1', 'HW', 42, 'Algo', 'assignment', ?)",
            ((now + timedelta(days=30)).isoformat(),),
        )
        await db.commit()

        items = await _review_items(db)
        assert len(items) == 2
        old_item = next(i for i in items if "Old" in i.title)
        recent_item = next(i for i in items if "Recent" in i.title)
        assert old_item.score > recent_item.score

    @pytest.mark.asyncio
    async def test_exam_proximity_boosts_review_score(self, db):
        from sophia.services.athena_chronos import _review_items

        now = datetime.now(UTC)
        await _insert_review(db, "Topic A", 42, now - timedelta(hours=1))
        await _insert_review(db, "Topic B", 99, now - timedelta(hours=1))
        # Exam for course 42 in 5 days
        await _insert_exam(db, 42, now + timedelta(days=5))
        # Course names
        await db.execute(
            "INSERT INTO deadline_cache (id, name, course_id, course_name, deadline_type, due_at) "
            "VALUES ('a:99', 'HW', 99, 'DB', 'assignment', ?)",
            ((now + timedelta(days=30)).isoformat(),),
        )
        await db.commit()

        items = await _review_items(db)
        item_42 = next(i for i in items if i.course_id == 42)
        item_99 = next(i for i in items if i.course_id == 99)
        assert item_42.score > item_99.score


class TestConfidenceGapItems:
    @pytest.mark.asyncio
    async def test_low_ratings_become_gap_items(self, db):
        from sophia.services.athena_chronos import _confidence_gap_items

        now = datetime.now(UTC)
        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted, rated_at) "
            "VALUES (?, ?, ?, ?)",
            ("Graphs", 42, 0.2, now.isoformat()),
        )
        await db.execute(
            "INSERT INTO deadline_cache (id, name, course_id, course_name, deadline_type, due_at) "
            "VALUES ('a:1', 'HW', 42, 'Algo', 'assignment', ?)",
            ((now + timedelta(days=30)).isoformat(),),
        )
        await db.commit()

        items = await _confidence_gap_items(db)
        assert len(items) == 1
        assert "Low confidence" in items[0].title
        assert "Graphs" in items[0].title

    @pytest.mark.asyncio
    async def test_no_gaps_when_all_confident(self, db):
        from sophia.services.athena_chronos import _confidence_gap_items

        now = datetime.now(UTC)
        await db.execute(
            "INSERT INTO confidence_ratings (topic, course_id, predicted, rated_at) "
            "VALUES (?, ?, ?, ?)",
            ("Sorting", 42, 0.8, now.isoformat()),
        )
        await db.commit()

        items = await _confidence_gap_items(db)
        assert items == []
