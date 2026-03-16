"""Tests for the study CLI command group (Athena Phase 4.0+)."""

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


class TestStudyAppRegistration:
    """The study app must be registered on the root CLI."""

    def test_study_app_exists(self) -> None:
        from sophia.__main__ import study_app

        assert "study" in study_app.name

    def test_study_app_help_mentions_athena(self) -> None:
        from sophia.__main__ import study_app

        help_text = study_app.help if isinstance(study_app.help, str) else ""  # pyright: ignore[reportUnnecessaryIsInstance]
        assert "Athena" in help_text


class TestStudyTopicsCommand:
    """The `sophia study topics` command extracts and displays topics."""

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
        from sophia.__main__ import study_topics

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.extract_topics_from_lectures",
                return_value=[],
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await study_topics(module_id=42)

    @pytest.mark.asyncio
    async def test_topics_success_calls_extract_and_link(
        self,
        mock_container: MagicMock,
        sample_topics: list[TopicMapping],
        sample_chunks: dict[str, list[tuple[KnowledgeChunk, float]]],
    ) -> None:
        """Topics command should call extract then link, and not raise."""
        from sophia.__main__ import study_topics

        mock_cursor = AsyncMock()
        mock_cursor.fetchall = AsyncMock(return_value=[("ep1", "Lecture 1")])

        # study_topics now makes additional DB calls:
        # 1. episode title lookup (fetchall)
        # 2. series title lookup (fetchone → single row)
        # 3. get_course_references query (fetchall → empty)
        series_cursor = AsyncMock()
        series_cursor.fetchone = AsyncMock(return_value=("Lecture 1",))
        refs_cursor = AsyncMock()
        refs_cursor.fetchall = AsyncMock(return_value=[])
        mock_container.db.execute = AsyncMock(side_effect=[mock_cursor, series_cursor, refs_cursor])

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

            await study_topics(module_id=42)

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
        from sophia.__main__ import study_topics
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
                await study_topics(module_id=42)

    @pytest.mark.asyncio
    async def test_topics_extraction_error_exits_1(self, mock_container: MagicMock) -> None:
        """TopicExtractionError should print message and exit with code 1."""
        from sophia.__main__ import study_topics
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
                await study_topics(module_id=42)

    @pytest.mark.asyncio
    async def test_topics_embedding_error_exits_1(self, mock_container: MagicMock) -> None:
        """EmbeddingError should print message and exit with code 1."""
        from sophia.__main__ import study_topics
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
                await study_topics(module_id=42)


class TestStudyConfidenceCommand:
    """The `sophia study confidence` command runs the confidence workflow."""

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
        from sophia.__main__ import study_confidence

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.get_course_topics",
                return_value=[],
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await study_confidence(module_id=42)

    @pytest.mark.asyncio
    async def test_confidence_auth_error_exits_1(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import study_confidence
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
                await study_confidence(module_id=42)

    @pytest.mark.asyncio
    async def test_confidence_error_exits_1(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import study_confidence
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
                await study_confidence(module_id=42)

    @pytest.mark.asyncio
    async def test_confidence_rates_and_displays(
        self,
        mock_container: MagicMock,
        sample_topics: list[TopicMapping],
    ) -> None:
        """Success path: rates topics, then shows table."""
        from sophia.__main__ import study_confidence

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

            await study_confidence(module_id=42)

            mock_rate.assert_called_once_with(mock_container, "Sorting", 42, 4)


class TestStudyReviewCommand:
    """The `sophia study review` command reviews flashcards and updates calibration."""

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
        from sophia.__main__ import study_review

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.get_due_cards",
                return_value=[],
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await study_review(module_id=42)

    @pytest.mark.asyncio
    async def test_review_saves_attempts_and_calibrates(
        self,
        mock_container: MagicMock,
        sample_cards: list[StudentFlashcard],
    ) -> None:
        from sophia.__main__ import study_review

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
            patch("rich.prompt.Prompt.ask", side_effect=["", ""]),
            patch("rich.prompt.Confirm.ask", side_effect=[True, False]),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await study_review(module_id=42)

            assert mock_save.call_count == 2
            mock_calibrate.assert_called()

    @pytest.mark.asyncio
    async def test_review_card_review_error_exits_1(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import study_review
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
                await study_review(module_id=42)

    @pytest.mark.asyncio
    async def test_review_command_registered(self) -> None:
        """The review command should be registered on study_app."""
        from sophia.__main__ import study_app

        command_names = [cmd for cmd in study_app]
        # study_app is a cyclopts App — check it has a "review" command
        assert any("review" in str(cmd) for cmd in command_names)


class TestStudyExplainCommand:
    """The `sophia study explain` command prompts students to self-explain wrong answers."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        container = MagicMock()
        container.db = AsyncMock()
        return container

    @pytest.fixture
    def sample_wrong_cards(self) -> list[StudentFlashcard]:
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
        ]

    @pytest.mark.asyncio
    async def test_explain_no_wrong_cards_prints_message(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import study_explain

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.get_failed_review_cards",
                return_value=[],
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await study_explain(module_id=42)

    @pytest.mark.asyncio
    async def test_explain_full_scaffold_collects_3_responses(
        self,
        mock_container: MagicMock,
        sample_wrong_cards: list[StudentFlashcard],
    ) -> None:
        from sophia.__main__ import study_explain

        mock_exp = MagicMock()
        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.get_failed_review_cards",
                return_value=sample_wrong_cards,
            ),
            patch(
                "sophia.services.athena_study.get_explanation_count",
                return_value=5,
            ),
            patch(
                "sophia.services.athena_study.save_self_explanation",
                return_value=mock_exp,
            ) as mock_save,
            patch(
                "sophia.services.athena_study.get_lecture_context",
                return_value="Lecture says quicksort is...",
            ),
            patch("rich.prompt.Prompt.ask", return_value="My explanation"),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await study_explain(module_id=42)

            mock_save.assert_called_once()
            # scaffold_level=3 for count=5
            assert mock_save.call_args.kwargs["scaffold_level"] == 3

    @pytest.mark.asyncio
    async def test_explain_open_scaffold_at_20_explanations(
        self,
        mock_container: MagicMock,
    ) -> None:
        from sophia.__main__ import study_explain

        wrong_card = StudentFlashcard(
            id=1,
            course_id=42,
            topic="Sorting",
            front="What is quicksort?",
            back="Divide-and-conquer sort",
            source=FlashcardSource.STUDY,
            created_at="2026-01-01",
        )

        mock_exp = MagicMock()
        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_study.get_failed_review_cards",
                return_value=[wrong_card],
            ),
            patch(
                "sophia.services.athena_study.get_explanation_count",
                return_value=25,
            ),
            patch(
                "sophia.services.athena_study.save_self_explanation",
                return_value=mock_exp,
            ) as mock_save,
            patch(
                "sophia.services.athena_study.get_lecture_context",
                return_value="Lecture context...",
            ),
            patch("rich.prompt.Prompt.ask", return_value="My open explanation"),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await study_explain(module_id=42)

            mock_save.assert_called_once()
            # At 25 explanations, scaffold_level should be 0
            assert mock_save.call_args.kwargs["scaffold_level"] == 0

    @pytest.mark.asyncio
    async def test_explain_command_registered(self) -> None:
        """The explain command should be registered on study_app."""
        from sophia.__main__ import study_app

        command_names = [cmd for cmd in study_app]
        assert any("explain" in str(cmd) for cmd in command_names)


class TestStudyExportCommand:
    """The `sophia study export` command exports flashcards as .apkg."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        container = MagicMock()
        container.db = AsyncMock()
        return container

    @pytest.mark.asyncio
    async def test_export_anki_success(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import study_export

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_export.export_anki_deck",
                return_value=5,
            ) as mock_export,
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await study_export(module_id=42)

            mock_export.assert_called_once()

    @pytest.mark.asyncio
    async def test_export_anki_no_cards(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import study_export

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_export.export_anki_deck",
                return_value=0,
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await study_export(module_id=42)

    @pytest.mark.asyncio
    async def test_export_anki_registered(self) -> None:
        """The export command should be registered on study_app."""
        from sophia.__main__ import study_app

        command_names = [cmd for cmd in study_app]
        assert any("export" in str(cmd) for cmd in command_names)


class TestStudyDueCommand:
    """The `sophia study due` command shows due and upcoming reviews."""

    @pytest.fixture
    def mock_container(self) -> MagicMock:
        container = MagicMock()
        container.db = AsyncMock()
        return container

    @pytest.mark.asyncio
    async def test_review_check_with_due_reviews(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import study_due
        from sophia.domain.models import ReviewSchedule

        due = [
            ReviewSchedule(
                topic="Sorting",
                course_id=42,
                interval_index=1,
                next_review_at="2026-03-15T00:00:00+00:00",
                score_at_last_review=0.85,
            ),
        ]
        upcoming = [
            ReviewSchedule(
                topic="Hashing",
                course_id=42,
                interval_index=0,
                next_review_at="2026-03-18T00:00:00+00:00",
            ),
        ]

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_review.get_due_reviews",
                return_value=due,
            ) as mock_due,
            patch(
                "sophia.services.athena_review.get_upcoming_reviews",
                return_value=upcoming,
            ) as mock_upcoming,
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await study_due()

            mock_due.assert_called_once()
            mock_upcoming.assert_called_once()

    @pytest.mark.asyncio
    async def test_review_check_no_reviews(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import study_due

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_review.get_due_reviews",
                return_value=[],
            ),
            patch(
                "sophia.services.athena_review.get_upcoming_reviews",
                return_value=[],
            ),
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await study_due()

    @pytest.mark.asyncio
    async def test_review_check_with_module_filter(self, mock_container: MagicMock) -> None:
        from sophia.__main__ import study_due

        with (
            patch("sophia.infra.di.create_app") as mock_create,
            patch(
                "sophia.services.athena_review.get_due_reviews",
                return_value=[],
            ) as mock_due,
            patch(
                "sophia.services.athena_review.get_upcoming_reviews",
                return_value=[],
            ) as mock_upcoming,
        ):
            mock_create.return_value.__aenter__ = AsyncMock(return_value=mock_container)
            mock_create.return_value.__aexit__ = AsyncMock(return_value=False)

            await study_due(module_id=42)

            mock_due.assert_called_once_with(mock_container.db, course_id=42)
            mock_upcoming.assert_called_once_with(mock_container.db, course_id=42, days_ahead=3)

    @pytest.mark.asyncio
    async def test_review_check_command_registered(self) -> None:
        """The due command should be registered on study_app."""
        from sophia.__main__ import study_app

        command_names = [cmd for cmd in study_app]
        assert any("due" in str(cmd) for cmd in command_names)
