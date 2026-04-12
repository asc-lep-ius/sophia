"""Tests for quickstart service wrappers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from sophia.gui.services.quickstart_service import (
    get_completed_session_count,
    get_enrolled_courses,
    get_nearest_deadline,
    get_topics_for_courses,
    save_initial_confidence,
)

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer


# ---------------------------------------------------------------------------
# get_enrolled_courses
# ---------------------------------------------------------------------------


class TestGetEnrolledCourses:
    @pytest.mark.asyncio
    async def test_success(self, mock_container: AppContainer) -> None:
        from sophia.domain.models import Course

        courses = [
            Course(id=1, fullname="Math", shortname="MATH"),
            Course(id=2, fullname="Physics", shortname="PHYS"),
        ]
        mock_container.moodle.get_enrolled_courses = AsyncMock(return_value=courses)
        result = await get_enrolled_courses(mock_container)
        assert len(result) == 2
        assert result[0].fullname == "Math"

    @pytest.mark.asyncio
    async def test_error_returns_empty(self, mock_container: AppContainer) -> None:
        mock_container.moodle.get_enrolled_courses = AsyncMock(side_effect=RuntimeError("network"))
        result = await get_enrolled_courses(mock_container)
        assert result == []


# ---------------------------------------------------------------------------
# get_nearest_deadline
# ---------------------------------------------------------------------------


class TestGetNearestDeadline:
    @pytest.mark.asyncio
    async def test_success_with_deadlines(self, mock_container: AppContainer) -> None:
        from sophia.domain.models import Deadline, DeadlineType

        soon = datetime.now(UTC) + timedelta(days=2)
        later = datetime.now(UTC) + timedelta(days=10)
        deadlines = [
            Deadline(
                id="1",
                name="Quiz",
                course_id=1,
                course_name="Math",
                deadline_type=DeadlineType.QUIZ,
                due_at=soon,
            ),
            Deadline(
                id="2",
                name="Exam",
                course_id=1,
                course_name="Math",
                deadline_type=DeadlineType.EXAM,
                due_at=later,
            ),
        ]
        with patch(
            "sophia.gui.services.quickstart_service._get_deadlines",
            new_callable=AsyncMock,
            return_value=deadlines,
        ):
            result = await get_nearest_deadline(mock_container)
        assert result is not None
        assert result.name == "Quiz"

    @pytest.mark.asyncio
    async def test_empty_returns_none(self, mock_container: AppContainer) -> None:
        with patch(
            "sophia.gui.services.quickstart_service._get_deadlines",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await get_nearest_deadline(mock_container)
        assert result is None


# ---------------------------------------------------------------------------
# get_completed_session_count
# ---------------------------------------------------------------------------


class TestGetCompletedSessionCount:
    @pytest.mark.asyncio
    async def test_returns_count(self, mock_container: AppContainer) -> None:
        mock_cursor = AsyncMock()
        mock_cursor.fetchone = AsyncMock(return_value=(3,))
        mock_container.db.execute = AsyncMock(return_value=mock_cursor)

        result = await get_completed_session_count(mock_container)
        assert result == 3

    @pytest.mark.asyncio
    async def test_error_returns_zero(self, mock_container: AppContainer) -> None:
        mock_container.db.execute = AsyncMock(side_effect=RuntimeError("db error"))
        result = await get_completed_session_count(mock_container)
        assert result == 0


# ---------------------------------------------------------------------------
# get_topics_for_courses
# ---------------------------------------------------------------------------


class TestGetTopicsForCourses:
    @pytest.mark.asyncio
    async def test_fetches_and_flattens(self, mock_container: AppContainer) -> None:
        from sophia.domain.models import TopicMapping, TopicSource

        topics_c1 = [
            TopicMapping(topic="Algebra", course_id=1, source=TopicSource.LECTURE),
            TopicMapping(topic="Calculus", course_id=1, source=TopicSource.LECTURE),
        ]
        topics_c2 = [
            TopicMapping(topic="Mechanics", course_id=2, source=TopicSource.LECTURE),
        ]
        with patch(
            "sophia.gui.services.quickstart_service._get_course_topics",
            new_callable=AsyncMock,
            side_effect=[topics_c1, topics_c2],
        ):
            result = await get_topics_for_courses(mock_container, [1, 2])
        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_error_returns_empty(self, mock_container: AppContainer) -> None:
        with patch(
            "sophia.gui.services.quickstart_service._get_course_topics",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fail"),
        ):
            result = await get_topics_for_courses(mock_container, [1])
        assert result == []


# ---------------------------------------------------------------------------
# save_initial_confidence
# ---------------------------------------------------------------------------


class TestSaveInitialConfidence:
    @pytest.mark.asyncio
    async def test_saves_ratings(self, mock_container: AppContainer) -> None:
        ratings = {"Algebra": 3, "Calculus": 5}
        with patch(
            "sophia.gui.services.quickstart_service._rate_confidence",
            new_callable=AsyncMock,
        ) as mock_rate:
            await save_initial_confidence(mock_container, course_id=1, ratings=ratings)
        assert mock_rate.call_count == 2

    @pytest.mark.asyncio
    async def test_error_does_not_raise(self, mock_container: AppContainer) -> None:
        with patch(
            "sophia.gui.services.quickstart_service._rate_confidence",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db"),
        ):
            # Should not raise
            await save_initial_confidence(mock_container, course_id=1, ratings={"X": 1})
