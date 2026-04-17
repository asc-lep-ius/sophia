"""Tests for the Hermes search page — pure helpers, constants, and error handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# format_timestamp
# ---------------------------------------------------------------------------


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        ("seconds", "expected"),
        [
            (0, "00:00"),
            (5, "00:05"),
            (59, "00:59"),
            (60, "01:00"),
            (65, "01:05"),
            (600, "10:00"),
            (3599, "59:59"),
            (3600, "1:00:00"),
            (3661, "1:01:01"),
            (36000, "10:00:00"),
            (86399, "23:59:59"),
        ],
    )
    def test_formats_correctly(self, seconds: float, expected: str) -> None:
        from sophia.gui.pages.search import format_timestamp

        assert format_timestamp(seconds) == expected

    def test_fractional_seconds_truncated(self) -> None:
        from sophia.gui.pages.search import format_timestamp

        assert format_timestamp(65.9) == "01:05"

    def test_negative_treated_as_zero(self) -> None:
        from sophia.gui.pages.search import format_timestamp

        assert format_timestamp(-10) == "00:00"


# ---------------------------------------------------------------------------
# Bloom prompts
# ---------------------------------------------------------------------------


class TestBloomPrompts:
    def test_has_six_prompts(self) -> None:
        from sophia.gui.pages.search import _BLOOM_PROMPTS

        assert len(_BLOOM_PROMPTS) == 6

    def test_all_prompts_are_non_empty_strings(self) -> None:
        from sophia.gui.pages.search import _BLOOM_PROMPTS

        for prompt in _BLOOM_PROMPTS:
            assert isinstance(prompt, str)
            assert len(prompt) > 0

    def test_bloom_levels_cycle(self) -> None:
        """Verify 0→1→2→3→4→5→0 wrapping logic."""
        from sophia.gui.pages.search import _BLOOM_PROMPTS, _next_bloom_level

        level = 0
        for i in range(len(_BLOOM_PROMPTS)):
            assert level == i
            level = _next_bloom_level(level)
        assert level == 0  # wraps back


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_chunk_preview_length(self) -> None:
        from sophia.gui.pages.search import _CHUNK_PREVIEW_LENGTH

        assert _CHUNK_PREVIEW_LENGTH == 200

    def test_debounce_seconds(self) -> None:
        from sophia.gui.pages.search import _DEBOUNCE_SECONDS

        assert _DEBOUNCE_SECONDS > 0


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_search_content_callable(self) -> None:
        from sophia.gui.pages.search import search_content

        assert callable(search_content)


# ---------------------------------------------------------------------------
# _execute_search error handling
# ---------------------------------------------------------------------------


class TestExecuteSearch:
    """Test error handling in the async search execution path."""

    @pytest.mark.asyncio
    async def test_runtime_error_shows_notification(self) -> None:
        """RuntimeError from stale tab storage → ui.notify, no crash."""
        from sophia.gui.pages.search import _execute_search

        container = MagicMock()
        mock_result = MagicMock(
            episode_id=1,
            title="Lecture 1",
            chunk_text="text",
            start_time=0.0,
            end_time=60.0,
            score=0.9,
            source="test",
        )

        with (
            patch(
                "sophia.gui.pages.search.search_lectures",
                new_callable=AsyncMock,
                return_value=[mock_result],
            ),
            patch(
                "sophia.gui.pages.search._set_results",
                side_effect=RuntimeError("storage unavailable"),
            ),
            patch("sophia.gui.pages.search.ui") as mock_ui,
        ):
            await _execute_search(container, 1, "test query")

            mock_ui.notify.assert_called_once()
            call_kwargs = mock_ui.notify.call_args
            assert call_kwargs[1].get("type") == "negative" or "negative" in str(call_kwargs)

    @pytest.mark.asyncio
    async def test_domain_error_shows_notification(self) -> None:
        """EmbeddingError from search service → ui.notify with descriptive message."""
        from sophia.domain.errors import EmbeddingError
        from sophia.gui.pages.search import _execute_search

        container = MagicMock()

        with (
            patch(
                "sophia.gui.pages.search.search_lectures",
                new_callable=AsyncMock,
                side_effect=EmbeddingError("embedder not loaded"),
            ),
            patch("sophia.gui.pages.search.ui") as mock_ui,
        ):
            await _execute_search(container, 1, "test query")

            mock_ui.notify.assert_called_once()
            call_args = mock_ui.notify.call_args
            msg = call_args[0][0] if call_args[0] else call_args[1].get("message", "")
            assert "search" in msg.lower() or "error" in msg.lower()

    @pytest.mark.asyncio
    async def test_happy_path_sets_results(self) -> None:
        """Successful search → results stored, UI refreshed."""
        from sophia.gui.pages.search import _execute_search

        container = MagicMock()
        mock_result = MagicMock(
            episode_id=1,
            title="Lecture 1",
            chunk_text="text",
            start_time=0.0,
            end_time=60.0,
            score=0.9,
            source="test",
        )

        with (
            patch(
                "sophia.gui.pages.search.search_lectures",
                new_callable=AsyncMock,
                return_value=[mock_result],
            ),
            patch("sophia.gui.pages.search._set_results") as mock_set,
            patch("sophia.gui.pages.search._set_selected_index"),
            patch("sophia.gui.pages.search._set_bloom_response"),
            patch("sophia.gui.pages.search._search_results"),
        ):
            await _execute_search(container, 1, "test query")

            mock_set.assert_called_once()
            stored = mock_set.call_args[0][0]
            assert len(stored) == 1
            assert stored[0]["title"] == "Lecture 1"

    @pytest.mark.asyncio
    async def test_hermes_error_shows_notification(self) -> None:
        """HermesError from search service → inline error notification."""
        from sophia.domain.errors import HermesError
        from sophia.gui.pages.search import _execute_search

        container = MagicMock()

        with (
            patch(
                "sophia.gui.pages.search.search_lectures",
                new_callable=AsyncMock,
                side_effect=HermesError("ChromaDB offline"),
            ),
            patch("sophia.gui.pages.search.ui") as mock_ui,
        ):
            await _execute_search(container, 1, "test query")

            mock_ui.notify.assert_called_once()


# ---------------------------------------------------------------------------
# search_service wrapper
# ---------------------------------------------------------------------------


class TestSearchService:
    """Test that the service wrapper propagates domain errors."""

    @pytest.mark.asyncio
    async def test_sophia_error_propagates(self) -> None:
        """SophiaError subtypes must not be swallowed — they propagate to caller."""
        from sophia.domain.errors import EmbeddingError
        from sophia.gui.services.search_service import search_lectures

        container = MagicMock()

        with (
            patch(
                "sophia.gui.services.search_service._search_lectures",
                new_callable=AsyncMock,
                side_effect=EmbeddingError("embedder failed"),
            ),
            pytest.raises(EmbeddingError, match="embedder failed"),
        ):
            await search_lectures(container, 1, "test")

    @pytest.mark.asyncio
    async def test_unexpected_error_caught(self) -> None:
        """Non-domain errors are caught, logged, and return empty list."""
        from sophia.gui.services.search_service import search_lectures

        container = MagicMock()

        with patch(
            "sophia.gui.services.search_service._search_lectures",
            new_callable=AsyncMock,
            side_effect=ConnectionError("network down"),
        ):
            result = await search_lectures(container, 1, "test")
            assert result == []

    @pytest.mark.asyncio
    async def test_happy_path_returns_results(self) -> None:
        """Successful search returns results unmodified."""
        from sophia.gui.services.search_service import search_lectures

        container = MagicMock()
        expected = [MagicMock()]

        with patch(
            "sophia.gui.services.search_service._search_lectures",
            new_callable=AsyncMock,
            return_value=expected,
        ):
            result = await search_lectures(container, 1, "test")
            assert result is expected

    def test_format_timestamp_callable(self) -> None:
        from sophia.gui.pages.search import format_timestamp

        assert callable(format_timestamp)
