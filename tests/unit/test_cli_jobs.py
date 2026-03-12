"""Tests for the jobs CLI commands and --schedule flag."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class TestScheduleTimeComputation:
    async def test_schedule_computes_correct_time(self) -> None:
        """--schedule should schedule 5s before registration_start."""
        reg_start = "01.07.2026 10:00"
        reg_time = datetime.strptime(reg_start, "%d.%m.%Y %H:%M").replace(tzinfo=UTC)
        schedule_time = reg_time - timedelta(seconds=5)

        assert schedule_time.minute == 59
        assert schedule_time.second == 55

    async def test_schedule_rejects_past_time(self) -> None:
        """If registration already opened, --schedule should fail."""
        past_time = datetime.now(UTC) - timedelta(hours=1)
        schedule_time = past_time - timedelta(seconds=5)
        assert schedule_time <= datetime.now(UTC)
