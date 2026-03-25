"""Tests for the Chronos deadlines page — pure helpers and constants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

# ---------------------------------------------------------------------------
# format_due_date
# ---------------------------------------------------------------------------


class TestFormatDueDate:
    @pytest.mark.parametrize(
        ("delta_days", "expected_contains"),
        [
            (3, "in 3 days"),
            (1, "in 1 day"),
            (0, "today"),
            (-1, "overdue by 1 day"),
            (-5, "overdue by 5 days"),
        ],
    )
    def test_relative_formatting(self, delta_days: int, expected_contains: str) -> None:
        from sophia.gui.pages.chronos import format_due_date

        now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)
        due = now + timedelta(days=delta_days)
        result = format_due_date(due, now=now)
        assert expected_contains in result

    def test_defaults_to_utcnow_when_now_omitted(self) -> None:
        from sophia.gui.pages.chronos import format_due_date

        far_future = datetime(2099, 1, 1, tzinfo=UTC)
        result = format_due_date(far_future)
        assert "in" in result

    def test_large_overdue(self) -> None:
        from sophia.gui.pages.chronos import format_due_date

        now = datetime(2026, 3, 25, 12, 0, tzinfo=UTC)
        due = now - timedelta(days=30)
        result = format_due_date(due, now=now)
        assert "overdue by 30 days" in result


# ---------------------------------------------------------------------------
# format_hours
# ---------------------------------------------------------------------------


class TestFormatHours:
    @pytest.mark.parametrize(
        ("hours", "expected"),
        [
            (0, "0min"),
            (0.5, "30min"),
            (1.0, "1.0h"),
            (1.5, "1.5h"),
            (2.25, "2.2h"),
        ],
    )
    def test_formats_correctly(self, hours: float, expected: str) -> None:
        from sophia.gui.pages.chronos import format_hours

        assert format_hours(hours) == expected

    def test_small_fractional_shows_minutes(self) -> None:
        from sophia.gui.pages.chronos import format_hours

        assert format_hours(0.25) == "15min"

    def test_exactly_one_hour(self) -> None:
        from sophia.gui.pages.chronos import format_hours

        assert format_hours(1.0) == "1.0h"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestDeadlineTypeColors:
    def test_has_all_types(self) -> None:
        from sophia.gui.pages.chronos import _DEADLINE_TYPE_COLORS

        assert len(_DEADLINE_TYPE_COLORS) == 5

    def test_assignment_is_green(self) -> None:
        from sophia.gui.pages.chronos import _DEADLINE_TYPE_COLORS

        assert _DEADLINE_TYPE_COLORS["assignment"] == "green"

    def test_quiz_is_blue(self) -> None:
        from sophia.gui.pages.chronos import _DEADLINE_TYPE_COLORS

        assert _DEADLINE_TYPE_COLORS["quiz"] == "blue"

    def test_exam_is_red(self) -> None:
        from sophia.gui.pages.chronos import _DEADLINE_TYPE_COLORS

        assert _DEADLINE_TYPE_COLORS["exam"] == "red"

    def test_exam_registration_is_orange(self) -> None:
        from sophia.gui.pages.chronos import _DEADLINE_TYPE_COLORS

        assert _DEADLINE_TYPE_COLORS["exam_registration"] == "orange"

    def test_checkmark_is_teal(self) -> None:
        from sophia.gui.pages.chronos import _DEADLINE_TYPE_COLORS

        assert _DEADLINE_TYPE_COLORS["checkmark"] == "teal"


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class TestExports:
    def test_chronos_content_callable(self) -> None:
        from sophia.gui.pages.chronos import chronos_content

        assert callable(chronos_content)

    def test_format_due_date_callable(self) -> None:
        from sophia.gui.pages.chronos import format_due_date

        assert callable(format_due_date)

    def test_format_hours_callable(self) -> None:
        from sophia.gui.pages.chronos import format_hours

        assert callable(format_hours)
