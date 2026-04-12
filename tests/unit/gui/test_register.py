"""Tests for the registration page — pure helpers and constants."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sophia.domain.models import RegistrationStatus

# ---------------------------------------------------------------------------
# status_badge_color
# ---------------------------------------------------------------------------


class TestStatusBadgeColor:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (RegistrationStatus.OPEN, "green"),
            (RegistrationStatus.REGISTERED, "blue"),
            (RegistrationStatus.PENDING, "yellow"),
            (RegistrationStatus.FULL, "red"),
            (RegistrationStatus.CLOSED, "gray"),
            (RegistrationStatus.FAILED, "red"),
        ],
    )
    def test_maps_status_to_color(self, status: RegistrationStatus, expected: str) -> None:
        from sophia.gui.pages.register import status_badge_color

        assert status_badge_color(status) == expected

    def test_unknown_status_returns_gray(self) -> None:
        from sophia.gui.pages.register import status_badge_color

        assert status_badge_color("unknown") == "gray"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# format_countdown
# ---------------------------------------------------------------------------


class TestFormatCountdown:
    def test_opens_in_future(self) -> None:
        from sophia.gui.pages.register import format_countdown

        now = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
        opens = "01.03.2026 08:30"
        result = format_countdown(opens, now=now)
        assert result == "Opens in 2h 30m"

    def test_already_open(self) -> None:
        from sophia.gui.pages.register import format_countdown

        now = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
        opens = "01.03.2026 08:00"
        result = format_countdown(opens, now=now)
        assert result == "Open now"

    def test_no_start_time(self) -> None:
        from sophia.gui.pages.register import format_countdown

        result = format_countdown(None)
        assert result == ""

    def test_opens_in_days(self) -> None:
        from sophia.gui.pages.register import format_countdown

        now = datetime(2026, 2, 27, 12, 0, tzinfo=UTC)
        opens = "01.03.2026 08:00"
        result = format_countdown(opens, now=now)
        assert "1d" in result

    def test_opens_in_minutes_only(self) -> None:
        from sophia.gui.pages.register import format_countdown

        now = datetime(2026, 3, 1, 7, 45, tzinfo=UTC)
        opens = "01.03.2026 08:00"
        result = format_countdown(opens, now=now)
        assert result == "Opens in 15m"


# ---------------------------------------------------------------------------
# format_capacity
# ---------------------------------------------------------------------------


class TestFormatCapacity:
    def test_normal_capacity(self) -> None:
        from sophia.gui.pages.register import format_capacity

        assert format_capacity(23, 30) == "23/30"

    def test_full_capacity(self) -> None:
        from sophia.gui.pages.register import format_capacity

        assert format_capacity(30, 30) == "30/30"

    def test_zero_capacity(self) -> None:
        from sophia.gui.pages.register import format_capacity

        assert format_capacity(0, 0) == "0/0"
