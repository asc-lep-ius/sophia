"""Tests for the jobs section display helpers in Settings page."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from sophia.gui.pages.settings import format_duration, format_elapsed, job_status_badge

# ---------------------------------------------------------------------------
# job_status_badge — status → (label, color, icon) mapping
# ---------------------------------------------------------------------------


class TestJobStatusBadge:
    @pytest.mark.parametrize(
        ("status", "expected_color", "expected_icon"),
        [
            ("queued", "gray", "hourglass_empty"),
            ("running", "blue", "sync"),
            ("completed", "green", "check_circle"),
            ("failed", "red", "error"),
            ("cancelled", "orange", "cancel"),
        ],
    )
    def test_returns_correct_badge(
        self, status: str, expected_color: str, expected_icon: str
    ) -> None:
        label, color, icon = job_status_badge(status)
        assert label == status.capitalize()
        assert color == expected_color
        assert icon == expected_icon

    def test_unknown_status_returns_gray(self) -> None:
        _label, color, _icon = job_status_badge("unknown_status")
        assert color == "gray"


# ---------------------------------------------------------------------------
# format_elapsed — running time for active jobs
# ---------------------------------------------------------------------------


class TestFormatElapsed:
    def test_seconds_only(self) -> None:
        started = datetime.now(UTC) - timedelta(seconds=45)
        result = format_elapsed(started)
        assert result == "< 1m"

    def test_minutes(self) -> None:
        started = datetime.now(UTC) - timedelta(minutes=5, seconds=30)
        result = format_elapsed(started)
        assert result == "5m"

    def test_hours_and_minutes(self) -> None:
        started = datetime.now(UTC) - timedelta(hours=2, minutes=15)
        result = format_elapsed(started)
        assert result == "2h 15m"

    def test_none_returns_dash(self) -> None:
        assert format_elapsed(None) == "—"


# ---------------------------------------------------------------------------
# format_duration — completed job duration
# ---------------------------------------------------------------------------


class TestFormatDuration:
    def test_full_duration(self) -> None:
        started = datetime(2026, 4, 12, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 4, 12, 10, 5, 30, tzinfo=UTC)
        result = format_duration(started, completed)
        assert result == "5m 30s"

    def test_seconds_only_duration(self) -> None:
        started = datetime(2026, 4, 12, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 4, 12, 10, 0, 12, tzinfo=UTC)
        result = format_duration(started, completed)
        assert result == "12s"

    def test_hours_duration(self) -> None:
        started = datetime(2026, 4, 12, 10, 0, 0, tzinfo=UTC)
        completed = datetime(2026, 4, 12, 12, 30, 0, tzinfo=UTC)
        result = format_duration(started, completed)
        assert result == "2h 30m"

    def test_none_started_returns_dash(self) -> None:
        assert format_duration(None, datetime.now(UTC)) == "—"

    def test_none_completed_returns_dash(self) -> None:
        assert format_duration(datetime.now(UTC), None) == "—"
