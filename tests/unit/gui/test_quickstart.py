"""Tests for quickstart wizard pure helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sophia.gui.pages.quickstart import (
    compute_scaffold_level,
    format_confidence_prompt,
    suggest_first_action,
)

# ---------------------------------------------------------------------------
# compute_scaffold_level
# ---------------------------------------------------------------------------


class TestComputeScaffoldLevel:
    """Scaffold fading: 0→3 (full), 3→2, 5→1, 10→0."""

    @pytest.mark.parametrize(
        ("session_count", "expected"),
        [
            (0, 3),
            (1, 3),
            (2, 3),
            (3, 2),
            (4, 2),
            (5, 1),
            (9, 1),
            (10, 0),
            (100, 0),
        ],
    )
    def test_thresholds(self, session_count: int, expected: int) -> None:
        assert compute_scaffold_level(session_count) == expected


# ---------------------------------------------------------------------------
# suggest_first_action
# ---------------------------------------------------------------------------


class TestSuggestFirstAction:
    def test_with_deadlines_picks_nearest(self) -> None:
        soon = datetime.now(UTC) + timedelta(days=3)
        later = datetime.now(UTC) + timedelta(days=10)
        deadlines = [
            {"name": "Quiz 1", "due_at": later},
            {"name": "Homework", "due_at": soon},
        ]
        msg, path = suggest_first_action(deadlines, topics=[])
        assert "Homework" in msg
        assert "day" in msg
        assert path == "/chronos"

    def test_with_topics_only(self) -> None:
        msg, path = suggest_first_action(deadlines=[], topics=["Linear Algebra", "Calculus"])
        assert "study session" in msg.lower()
        assert path == "/study"

    def test_with_nothing(self) -> None:
        msg, path = suggest_first_action(deadlines=[], topics=[])
        assert "settings" in msg.lower() or "sync" in msg.lower()
        assert path == "/settings"

    def test_deadlines_take_priority_over_topics(self) -> None:
        soon = datetime.now(UTC) + timedelta(days=5)
        deadlines = [{"name": "Exam", "due_at": soon}]
        msg, path = suggest_first_action(deadlines, topics=["Topic A"])
        assert "Exam" in msg
        assert path == "/chronos"


# ---------------------------------------------------------------------------
# format_confidence_prompt
# ---------------------------------------------------------------------------


class TestFormatConfidencePrompt:
    def test_full_scaffold(self) -> None:
        text = format_confidence_prompt(3)
        assert len(text) > 0
        # Full scaffold should have the most explanatory text
        assert "predict" in text.lower() or "confidence" in text.lower()

    def test_abbreviated_scaffold(self) -> None:
        text = format_confidence_prompt(2)
        assert len(text) > 0

    def test_minimal_scaffold(self) -> None:
        text = format_confidence_prompt(1)
        assert len(text) > 0

    def test_open_scaffold(self) -> None:
        text = format_confidence_prompt(0)
        assert len(text) > 0

    def test_levels_differ(self) -> None:
        texts = {format_confidence_prompt(level) for level in range(4)}
        assert len(texts) >= 3  # at least 3 distinct prompts
