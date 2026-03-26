"""Tests for the Hermes search page — pure helpers and constants."""

from __future__ import annotations

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

    def test_format_timestamp_callable(self) -> None:
        from sophia.gui.pages.search import format_timestamp

        assert callable(format_timestamp)
