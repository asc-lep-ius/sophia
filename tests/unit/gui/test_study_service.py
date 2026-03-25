"""Tests for GUI study service wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from sophia.domain.errors import TopicExtractionError
from sophia.domain.models import ConfidenceRating, DifficultyLevel

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer

TOPIC = "Binary Search"
COURSE_ID = 42

_PATCH_BASE = "sophia.gui.services.study_service"


# -- fixtures ----------------------------------------------------------------


@pytest.fixture
def _mock_confidence(mock_container: AppContainer):
    """Patch get_confidence_ratings to return a known rating for TOPIC."""
    rating = ConfidenceRating(
        topic=TOPIC,
        course_id=COURSE_ID,
        predicted=0.8,
        rated_at="2026-01-01T00:00:00",
    )
    with (
        patch(
            f"{_PATCH_BASE}.get_confidence_ratings",
            new_callable=AsyncMock,
            return_value=[rating],
        ),
        patch(f"{_PATCH_BASE}.get_topic_difficulty_level", return_value=DifficultyLevel.TRANSFER),
    ):
        yield


@pytest.fixture
def _mock_confidence_empty(mock_container: AppContainer):
    """Patch get_confidence_ratings to return an empty list (no prior ratings)."""
    with (
        patch(f"{_PATCH_BASE}.get_confidence_ratings", new_callable=AsyncMock, return_value=[]),
        patch(f"{_PATCH_BASE}.get_topic_difficulty_level", return_value=DifficultyLevel.EXPLAIN),
    ):
        yield


# -- get_pretest_questions ---------------------------------------------------


class TestGetPretestQuestions:
    """Tests for get_pretest_questions."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_confidence")
    async def test_returns_generated_questions_and_difficulty(
        self, mock_container: AppContainer
    ) -> None:
        from sophia.gui.services.study_service import get_pretest_questions

        questions = ["Q1", "Q2", "Q3"]
        with patch(
            f"{_PATCH_BASE}.generate_study_questions",
            new_callable=AsyncMock,
            return_value=questions,
        ):
            result_qs, difficulty = await get_pretest_questions(mock_container, COURSE_ID, TOPIC)

        assert result_qs == questions
        assert difficulty is DifficultyLevel.TRANSFER

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_confidence")
    async def test_falls_back_on_topic_extraction_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import get_pretest_questions

        with patch(
            f"{_PATCH_BASE}.generate_study_questions",
            new_callable=AsyncMock,
            side_effect=TopicExtractionError("boom"),
        ):
            result_qs, difficulty = await get_pretest_questions(mock_container, COURSE_ID, TOPIC)

        assert len(result_qs) == 3
        assert all(TOPIC in q for q in result_qs)
        assert difficulty is DifficultyLevel.TRANSFER

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_confidence_empty")
    async def test_no_ratings_defaults_to_explain(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import get_pretest_questions

        questions = ["Q1", "Q2", "Q3"]
        with patch(
            f"{_PATCH_BASE}.generate_study_questions",
            new_callable=AsyncMock,
            return_value=questions,
        ):
            _, difficulty = await get_pretest_questions(mock_container, COURSE_ID, TOPIC)

        assert difficulty is DifficultyLevel.EXPLAIN

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_confidence")
    async def test_custom_count(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import get_pretest_questions

        questions = ["Q1", "Q2", "Q3", "Q4", "Q5"]
        with patch(
            f"{_PATCH_BASE}.generate_study_questions",
            new_callable=AsyncMock,
            return_value=questions,
        ) as mock_gen:
            result_qs, _ = await get_pretest_questions(mock_container, COURSE_ID, TOPIC, count=5)

        assert result_qs == questions
        mock_gen.assert_awaited_once()
        call_kwargs = mock_gen.call_args
        assert call_kwargs[1]["count"] == 5


# -- get_study_material ------------------------------------------------------


class TestGetStudyMaterial:
    """Tests for get_study_material."""

    @pytest.mark.asyncio
    async def test_returns_lecture_text(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import get_study_material

        lecture = "Here is the lecture content about Binary Search..."
        with patch(
            f"{_PATCH_BASE}.get_lecture_context",
            new_callable=AsyncMock,
            return_value=lecture,
        ):
            result = await get_study_material(mock_container, COURSE_ID, TOPIC)

        assert result == lecture

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_content(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import get_study_material

        with patch(
            f"{_PATCH_BASE}.get_lecture_context",
            new_callable=AsyncMock,
            return_value="",
        ):
            result = await get_study_material(mock_container, COURSE_ID, TOPIC)

        assert result == ""


# -- get_posttest_questions --------------------------------------------------


class TestGetPosttestQuestions:
    """Tests for get_posttest_questions."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_confidence")
    async def test_returns_generated_questions_and_difficulty(
        self, mock_container: AppContainer
    ) -> None:
        from sophia.gui.services.study_service import get_posttest_questions

        questions = ["PQ1", "PQ2", "PQ3"]
        with patch(
            f"{_PATCH_BASE}.generate_study_questions",
            new_callable=AsyncMock,
            return_value=questions,
        ):
            result_qs, difficulty = await get_posttest_questions(mock_container, COURSE_ID, TOPIC)

        assert result_qs == questions
        assert difficulty is DifficultyLevel.TRANSFER

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_confidence")
    async def test_falls_back_on_topic_extraction_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import get_posttest_questions

        with patch(
            f"{_PATCH_BASE}.generate_study_questions",
            new_callable=AsyncMock,
            side_effect=TopicExtractionError("boom"),
        ):
            result_qs, difficulty = await get_posttest_questions(mock_container, COURSE_ID, TOPIC)

        assert len(result_qs) == 3
        assert all(TOPIC in q for q in result_qs)
        assert difficulty is DifficultyLevel.TRANSFER

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_mock_confidence_empty")
    async def test_no_ratings_defaults_to_explain(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import get_posttest_questions

        questions = ["PQ1", "PQ2", "PQ3"]
        with patch(
            f"{_PATCH_BASE}.generate_study_questions",
            new_callable=AsyncMock,
            return_value=questions,
        ):
            _, difficulty = await get_posttest_questions(mock_container, COURSE_ID, TOPIC)

        assert difficulty is DifficultyLevel.EXPLAIN
