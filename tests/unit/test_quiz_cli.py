"""Tests for the quiz CLI command group (Athena Phase 4.0)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sophia.domain.models import KnowledgeChunk, TopicMapping, TopicSource


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
