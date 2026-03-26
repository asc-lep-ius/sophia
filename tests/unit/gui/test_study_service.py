"""Tests for GUI study service wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest

from sophia.domain.errors import TopicExtractionError
from sophia.domain.models import (
    ConfidenceRating,
    DifficultyLevel,
    ReviewSchedule,
    StudentFlashcard,
    StudySession,
    TopicMapping,
)

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


# -- select_interleave_topics -----------------------------------------------


class TestSelectInterleaveTopics:
    """Tests for select_interleave_topics."""

    @pytest.mark.asyncio
    async def test_blind_spots_first(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import select_interleave_topics

        blind = [
            ConfidenceRating(topic="T1", course_id=COURSE_ID, predicted=0.9, actual=0.3),
            ConfidenceRating(topic="T2", course_id=COURSE_ID, predicted=0.8, actual=0.2),
        ]
        with (
            patch(f"{_PATCH_BASE}.get_blind_spots", new_callable=AsyncMock, return_value=blind),
            patch(
                f"{_PATCH_BASE}._get_missed_lecture_topics",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(f"{_PATCH_BASE}.get_due_reviews", new_callable=AsyncMock, return_value=[]),
            patch(f"{_PATCH_BASE}.get_course_topics", new_callable=AsyncMock, return_value=[]),
        ):
            result = await select_interleave_topics(mock_container, COURSE_ID)

        assert result[:2] == ["T1", "T2"]

    @pytest.mark.asyncio
    async def test_fills_missed_lecture_topics(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import select_interleave_topics

        blind = [ConfidenceRating(topic="T1", course_id=COURSE_ID, predicted=0.9, actual=0.3)]
        with (
            patch(f"{_PATCH_BASE}.get_blind_spots", new_callable=AsyncMock, return_value=blind),
            patch(
                f"{_PATCH_BASE}._get_missed_lecture_topics",
                new_callable=AsyncMock,
                return_value=["Missed1", "Missed2"],
            ),
            patch(f"{_PATCH_BASE}.get_due_reviews", new_callable=AsyncMock, return_value=[]),
            patch(f"{_PATCH_BASE}.get_course_topics", new_callable=AsyncMock, return_value=[]),
        ):
            result = await select_interleave_topics(mock_container, COURSE_ID, max_topics=3)

        assert result == ["T1", "Missed1", "Missed2"]

    @pytest.mark.asyncio
    async def test_fills_due_reviews(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import select_interleave_topics

        due = [
            ReviewSchedule(topic="Due1", course_id=COURSE_ID, next_review_at="2026-01-01"),
            ReviewSchedule(topic="Due2", course_id=COURSE_ID, next_review_at="2026-01-02"),
        ]
        with (
            patch(f"{_PATCH_BASE}.get_blind_spots", new_callable=AsyncMock, return_value=[]),
            patch(
                f"{_PATCH_BASE}._get_missed_lecture_topics",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(f"{_PATCH_BASE}.get_due_reviews", new_callable=AsyncMock, return_value=due),
            patch(f"{_PATCH_BASE}.get_course_topics", new_callable=AsyncMock, return_value=[]),
        ):
            result = await select_interleave_topics(mock_container, COURSE_ID)

        assert result == ["Due1", "Due2"]

    @pytest.mark.asyncio
    async def test_fills_from_course_topics_when_fewer_than_two(
        self, mock_container: AppContainer
    ) -> None:
        from sophia.gui.services.study_service import select_interleave_topics

        all_topics = [
            TopicMapping(topic="A", course_id=COURSE_ID),
            TopicMapping(topic="B", course_id=COURSE_ID),
            TopicMapping(topic="C", course_id=COURSE_ID),
        ]
        with (
            patch(f"{_PATCH_BASE}.get_blind_spots", new_callable=AsyncMock, return_value=[]),
            patch(
                f"{_PATCH_BASE}._get_missed_lecture_topics",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(f"{_PATCH_BASE}.get_due_reviews", new_callable=AsyncMock, return_value=[]),
            patch(
                f"{_PATCH_BASE}.get_course_topics",
                new_callable=AsyncMock,
                return_value=all_topics,
            ),
        ):
            result = await select_interleave_topics(mock_container, COURSE_ID)

        assert result == ["A", "B", "C"]

    @pytest.mark.asyncio
    async def test_caps_at_max_topics(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import select_interleave_topics

        blind = [
            ConfidenceRating(topic=f"T{i}", course_id=COURSE_ID, predicted=0.9, actual=0.3)
            for i in range(5)
        ]
        with (
            patch(f"{_PATCH_BASE}.get_blind_spots", new_callable=AsyncMock, return_value=blind),
            patch(
                f"{_PATCH_BASE}._get_missed_lecture_topics",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(f"{_PATCH_BASE}.get_due_reviews", new_callable=AsyncMock, return_value=[]),
            patch(f"{_PATCH_BASE}.get_course_topics", new_callable=AsyncMock, return_value=[]),
        ):
            result = await select_interleave_topics(mock_container, COURSE_ID, max_topics=2)

        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_deduplicates_across_sources(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import select_interleave_topics

        blind = [ConfidenceRating(topic="T1", course_id=COURSE_ID, predicted=0.9, actual=0.3)]
        due = [ReviewSchedule(topic="T1", course_id=COURSE_ID, next_review_at="2026-01-01")]
        with (
            patch(f"{_PATCH_BASE}.get_blind_spots", new_callable=AsyncMock, return_value=blind),
            patch(
                f"{_PATCH_BASE}._get_missed_lecture_topics",
                new_callable=AsyncMock,
                return_value=["T1"],
            ),
            patch(f"{_PATCH_BASE}.get_due_reviews", new_callable=AsyncMock, return_value=due),
            patch(
                f"{_PATCH_BASE}.get_course_topics",
                new_callable=AsyncMock,
                return_value=[TopicMapping(topic="T2", course_id=COURSE_ID)],
            ),
        ):
            result = await select_interleave_topics(mock_container, COURSE_ID)

        assert result == ["T1", "T2"]


# -- check_novel_topic ------------------------------------------------------


class TestCheckNovelTopic:
    """Tests for check_novel_topic."""

    @pytest.mark.asyncio
    async def test_returns_true_when_no_sessions_and_no_confidence(
        self, mock_container: AppContainer
    ) -> None:
        from sophia.gui.services.study_service import check_novel_topic

        with (
            patch(f"{_PATCH_BASE}.get_study_sessions", new_callable=AsyncMock, return_value=[]),
            patch(f"{_PATCH_BASE}.get_confidence_ratings", new_callable=AsyncMock, return_value=[]),
        ):
            assert await check_novel_topic(mock_container, COURSE_ID, TOPIC) is True

    @pytest.mark.asyncio
    async def test_returns_false_when_prior_sessions_exist(
        self, mock_container: AppContainer
    ) -> None:
        from sophia.gui.services.study_service import check_novel_topic

        session = StudySession(id=1, course_id=COURSE_ID, topic=TOPIC, started_at="2026-01-01")
        with (
            patch(
                f"{_PATCH_BASE}.get_study_sessions",
                new_callable=AsyncMock,
                return_value=[session],
            ),
            patch(f"{_PATCH_BASE}.get_confidence_ratings", new_callable=AsyncMock, return_value=[]),
        ):
            assert await check_novel_topic(mock_container, COURSE_ID, TOPIC) is False

    @pytest.mark.asyncio
    async def test_returns_false_when_confidence_above_baseline(
        self, mock_container: AppContainer
    ) -> None:
        from sophia.gui.services.study_service import check_novel_topic

        rating = ConfidenceRating(
            topic=TOPIC, course_id=COURSE_ID, predicted=0.5, rated_at="2026-01-01"
        )
        with (
            patch(f"{_PATCH_BASE}.get_study_sessions", new_callable=AsyncMock, return_value=[]),
            patch(
                f"{_PATCH_BASE}.get_confidence_ratings",
                new_callable=AsyncMock,
                return_value=[rating],
            ),
        ):
            assert await check_novel_topic(mock_container, COURSE_ID, TOPIC) is False


# -- start_session -----------------------------------------------------------


class TestStartSession:
    """Tests for start_session wrapper."""

    @pytest.mark.asyncio
    async def test_delegates_to_start_study_session(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import start_session

        expected = StudySession(id=7, course_id=COURSE_ID, topic=TOPIC, started_at="2026-01-01")
        with patch(
            f"{_PATCH_BASE}.start_study_session",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_start:
            result = await start_session(mock_container, COURSE_ID, TOPIC)

        assert result == expected
        mock_start.assert_awaited_once_with(mock_container.db, COURSE_ID, TOPIC)


# -- complete_session --------------------------------------------------------


class TestCompleteSession:
    """Tests for complete_session wrapper."""

    @pytest.mark.asyncio
    async def test_delegates_to_complete_study_session(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import complete_session

        with patch(
            f"{_PATCH_BASE}.complete_study_session",
            new_callable=AsyncMock,
        ) as mock_complete:
            await complete_session(mock_container, session_id=7, pre_score=0.4, post_score=0.8)

        mock_complete.assert_awaited_once_with(mock_container.db, 7, 0.4, 0.8)


# -- save_study_flashcard ----------------------------------------------------


class TestSaveStudyFlashcard:
    """Tests for save_study_flashcard wrapper."""

    @pytest.mark.asyncio
    async def test_delegates_to_save_flashcard(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import save_study_flashcard

        expected = StudentFlashcard(id=1, course_id=COURSE_ID, topic=TOPIC, front="Q?", back="A.")
        with patch(
            f"{_PATCH_BASE}.save_flashcard",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_save:
            result = await save_study_flashcard(mock_container, COURSE_ID, TOPIC, "Q?", "A.")

        assert result == expected
        mock_save.assert_awaited_once_with(mock_container.db, COURSE_ID, TOPIC, "Q?", "A.")


# -- finalize_calibration ---------------------------------------------------


class TestFinalizeCalibration:
    """Tests for finalize_calibration."""

    @pytest.mark.asyncio
    async def test_updates_actual_score_and_calibration(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.study_service import finalize_calibration

        with (
            patch(f"{_PATCH_BASE}.update_actual_score", new_callable=AsyncMock) as mock_actual,
            patch(f"{_PATCH_BASE}.update_topic_calibration", new_callable=AsyncMock) as mock_calib,
        ):
            await finalize_calibration(mock_container, COURSE_ID, TOPIC, 0.75)

        mock_actual.assert_awaited_once_with(mock_container.db, TOPIC, COURSE_ID, 0.75)
        mock_calib.assert_awaited_once_with(mock_container.db, COURSE_ID, TOPIC)


# -- compute_score -----------------------------------------------------------


class TestComputeScore:
    """Tests for compute_score."""

    def test_fraction_of_non_empty_answers(self) -> None:
        from sophia.gui.services.study_service import compute_score

        answers = {"Q1": "yes", "Q2": "", "Q3": "sure"}
        questions = ["Q1", "Q2", "Q3"]
        assert compute_score(answers, questions) == pytest.approx(2 / 3)

    def test_all_empty_answers(self) -> None:
        from sophia.gui.services.study_service import compute_score

        answers = {"Q1": "", "Q2": "  "}
        questions = ["Q1", "Q2"]
        assert compute_score(answers, questions) == 0.0

    def test_empty_questions_list(self) -> None:
        from sophia.gui.services.study_service import compute_score

        assert compute_score({}, []) == 0.0


# -- format_improvement ------------------------------------------------------


class TestFormatImprovement:
    """Tests for format_improvement."""

    def test_positive_improvement(self) -> None:
        from sophia.gui.services.study_service import format_improvement

        assert format_improvement(0.4, 0.8) == "40% → 80% (+40%)"

    def test_negative_improvement(self) -> None:
        from sophia.gui.services.study_service import format_improvement

        assert format_improvement(0.8, 0.4) == "80% → 40% (-40%)"

    def test_no_change(self) -> None:
        from sophia.gui.services.study_service import format_improvement

        assert format_improvement(0.5, 0.5) == "50% → 50% (+0%)"
