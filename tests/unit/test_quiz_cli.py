"""Tests for the quiz CLI command group (Athena Phase 4.0+)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sophia.domain.models import (
    ConfidenceRating,
    FlashcardSource,
    KnowledgeChunk,
    StudentFlashcard,
    TopicMapping,
    TopicSource,
)


class TestQuizAppRegistration:
    """The quiz app must be registered on the root CLI."""

    def test_quiz_app_exists(self) -> None:
        from sophia.__main__ import quiz_app

        assert "quiz" in quiz_app.name

    def test_quiz_app_help_mentions_athena(self) -> None:
        from sophia.__main__ import quiz_app

        help_parts = quiz_app.help if isinstance(quiz_app.help, (list, tuple)) else [quiz_app.help]
        assert any("Athena" in (p or "") for p in help_parts)


class TestQuizTopicsCommand:
    """The `sophia quiz topics` command extracts and displays topics."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        container = MagicMock()
        container.db = AsyncMock()
        return container

    @pytest.fixture
    def sample_topics(self) -> list[TopicMapping]:
        return [
            TopicMapping(topic="Sorting", course_id=42, source=TopicSource.LECTURE, frequency=3),
            TopicMapping(topic="Hashing", course_id=42, source=TopicSource.LECTURE, frequency=1),
        ]

    @pytest.fixture
    def sample_chunks(self) -> dict[str, list[tuple[KnowledgeChunk, float]]]:
        chunk = KnowledgeChunk(
            chunk_id="c1",
            episode_id="ep1",
            chunk_index=0,
            text="Sorting algorithms overview",
            start_time=120.0,
            end_time=180.0,
        )
        return {"Sorting": [(chunk, 0.9)], "Hashing": []}

    @pytest.mark.asyncio
    async def test_topics_no_results(self, mock_container: MagicMock) -> None:
        """When no topics are extracted, print a helpful yellow message."""
        from sophia.__main__ import quiz_topics

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.extract_topics_from_lectures",
                return_value=[],
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await quiz_topics(module_id=42)

    @pytest.mark.asyncio
    async def test_topics_success_calls_extract_and_link(
        self,
        mock_container: MagicMock,
        sample_topics: list[TopicMapping],
        sample_chunks: dict[str, list[tuple[KnowledgeChunk, float]]],
    ) -> None:
        """Topics command should call extract then link, and not raise."""
        from sophia.__main__ import quiz_topics

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("ep1", "Lecture 1")])
        mock_container.db.execute = AsyncMock(return_value=mock_cursor)

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.extract_topics_from_lectures",
                return_value=sample_topics,
            ) as mock_extract,
            patch(
                "sophia.services.athena_study.link_topics_to_lectures",
                return_value=sample_chunks,
            ) as mock_link,
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await quiz_topics(module_id=42)

            mock_extract.assert_called_once_with(mock_container, 42)
            mock_link.assert_called_once_with(
                mock_container,
                42,
                42,
                ["Sorting", "Hashing"],
            )

    @pytest.mark.asyncio
    async def test_topics_auth_error_exits_1(self, mock_container: MagicMock) -> None:
        """AuthError should print message and exit with code 1."""
        from sophia.__main__ import quiz_topics
        from sophia.domain.errors import AuthError

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.extract_topics_from_lectures",
                side_effect=AuthError("expired"),
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(SystemExit, match="1"):
                await quiz_topics(module_id=42)

    @pytest.mark.asyncio
    async def test_topics_extraction_error_exits_1(self, mock_container: MagicMock) -> None:
        """TopicExtractionError should print message and exit with code 1."""
        from sophia.__main__ import quiz_topics
        from sophia.domain.errors import TopicExtractionError

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.extract_topics_from_lectures",
                side_effect=TopicExtractionError("LLM failed"),
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(SystemExit, match="1"):
                await quiz_topics(module_id=42)

    @pytest.mark.asyncio
    async def test_topics_embedding_error_exits_1(self, mock_container: MagicMock) -> None:
        """EmbeddingError should print message and exit with code 1."""
        from sophia.__main__ import quiz_topics
        from sophia.domain.errors import EmbeddingError

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.extract_topics_from_lectures",
                side_effect=EmbeddingError("vector DB down"),
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(SystemExit, match="1"):
                await quiz_topics(module_id=42)


class TestQuizConfidenceCommand:
    """The `sophia quiz confidence` command runs the confidence workflow."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        container = MagicMock()
        container.db = AsyncMock()
        return container

    @pytest.fixture
    def sample_topics(self) -> list[TopicMapping]:
        return [
            TopicMapping(topic="Sorting", course_id=42, source=TopicSource.LECTURE, frequency=3),
        ]

    @pytest.mark.asyncio
    async def test_confidence_no_topics_prints_message(self, mock_container: MagicMock) -> None:
        """When no topics exist, print a helpful yellow message."""
        from sophia.__main__ import quiz_confidence

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.get_course_topics",
                return_value=[],
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await quiz_confidence(module_id=42)

    @pytest.mark.asyncio
    async def test_confidence_auth_error_exits_1(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import quiz_confidence
        from sophia.domain.errors import AuthError

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.get_course_topics",
                side_effect=AuthError("expired"),
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(SystemExit, match="1"):
                await quiz_confidence(module_id=42)

    @pytest.mark.asyncio
    async def test_confidence_error_exits_1(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import quiz_confidence
        from sophia.domain.errors import ConfidenceError

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.get_course_topics",
                side_effect=ConfidenceError("bad"),
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(SystemExit, match="1"):
                await quiz_confidence(module_id=42)

    @pytest.mark.asyncio
    async def test_confidence_rates_and_displays(
        self,
        mock_container: MagicMock,
        sample_topics: list[TopicMapping],
    ) -> None:
        """Success path: rates topics, then shows table."""
        from sophia.__main__ import quiz_confidence

        rating = ConfidenceRating(
            topic="Sorting", course_id=42, predicted=0.75, rated_at="2026-01-01T00:00:00"
        )

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.get_course_topics",
                return_value=sample_topics,
            ),
            patch("rich.prompt.IntPrompt.ask", return_value=4),
            patch(
                "sophia.services.athena_confidence.rate_confidence",
                return_value=rating,
            ) as mock_rate,
            patch(
                "sophia.services.athena_confidence.get_confidence_ratings",
                return_value=[rating],
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await quiz_confidence(module_id=42)

            mock_rate.assert_called_once_with(mock_container, "Sorting", 42, 4)


class TestQuizReviewCommand:
    """The `sophia quiz review` command reviews flashcards and updates calibration."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        container = MagicMock()
        container.db = AsyncMock()
        return container

    @pytest.fixture
    def sample_cards(self) -> list[StudentFlashcard]:
        return [
            StudentFlashcard(
                id=1,
                course_id=42,
                topic="Sorting",
                front="What is quicksort?",
                back="Divide-and-conquer sort",
                source=FlashcardSource.STUDY,
                created_at="2026-01-01",
            ),
            StudentFlashcard(
                id=2,
                course_id=42,
                topic="Sorting",
                front="What is mergesort?",
                back="Stable divide-and-conquer",
                source=FlashcardSource.STUDY,
                created_at="2026-01-02",
            ),
        ]

    @pytest.mark.asyncio
    async def test_review_no_cards_prints_message(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import quiz_review

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.get_due_cards",
                return_value=[],
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await quiz_review(module_id=42)

    @pytest.mark.asyncio
    async def test_review_saves_attempts_and_calibrates(
        self,
        mock_container: MagicMock,
        sample_cards: list[StudentFlashcard],
    ) -> None:
        from sophia.__main__ import quiz_review

        mock_review_attempt = MagicMock()

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.get_due_cards",
                return_value=sample_cards,
            ),
            patch(
                "sophia.services.athena_study.save_review_attempt",
                return_value=mock_review_attempt,
            ) as mock_save,
            patch(
                "sophia.services.athena_study.update_topic_calibration",
            ) as mock_calibrate,
            patch(
                "sophia.services.athena_study.get_review_stats",
                return_value={
                    "total_reviews": 2,
                    "success_count": 1,
                    "success_rate": 0.5,
                },
            ),
            patch("rich.prompt.Prompt.ask", side_effect=["", "y", "", "n"]),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await quiz_review(module_id=42)

            assert mock_save.call_count == 2
            mock_calibrate.assert_called()

    @pytest.mark.asyncio
    async def test_review_card_review_error_exits_1(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import quiz_review
        from sophia.domain.errors import CardReviewError

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.get_due_cards",
                side_effect=CardReviewError("DB error"),
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(SystemExit, match="1"):
                await quiz_review(module_id=42)

    @pytest.mark.asyncio
    async def test_review_command_registered(self) -> None:
        """The review command should be registered on quiz_app."""
        from sophia.__main__ import quiz_app

        command_names = [cmd for cmd in quiz_app]
        # quiz_app is a cyclopts App — check it has a "review" command
        assert any("review" in str(cmd) for cmd in command_names)
