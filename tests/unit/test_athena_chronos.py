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
