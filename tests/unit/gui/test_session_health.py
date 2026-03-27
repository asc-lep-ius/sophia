"""Tests for session health monitoring with exponential backoff."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from sophia.gui.services.session_health import (
    _BACKOFF_BASE_S,
    _BACKOFF_CAP_S,
    SessionHealthMonitor,
)


@pytest.fixture
def healthy_check() -> AsyncMock:
    """SessionHealthCheck that always reports valid."""
    check = AsyncMock()
    check.is_session_valid.return_value = True
    return check


@pytest.fixture
def unhealthy_check() -> AsyncMock:
    """SessionHealthCheck that always reports invalid."""
    check = AsyncMock()
    check.is_session_valid.return_value = False
    return check


class TestSessionHealthMonitorInit:
    def test_starts_healthy(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=300)
        assert monitor.is_healthy is True

    def test_default_interval_stored(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=120)
        assert monitor._default_interval == 120

    def test_no_task_before_start(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check)
        assert monitor._task is None


class TestHealthCheck:
    async def test_healthy_check_stays_healthy(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=300)
        await monitor._check()
        assert monitor.is_healthy is True
        assert monitor._consecutive_failures == 0

    async def test_unhealthy_check_transitions_to_unhealthy(
        self,
        unhealthy_check: AsyncMock,
    ) -> None:
        monitor = SessionHealthMonitor(unhealthy_check, interval=300)
        await monitor._check()
        assert monitor.is_healthy is False
        assert monitor._consecutive_failures == 1

    async def test_recovery_resets_state(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=300)
        # Simulate prior failure state
        monitor._healthy = False
        monitor._consecutive_failures = 3
        await monitor._check()
        assert monitor.is_healthy is True
        assert monitor._consecutive_failures == 0

    async def test_last_check_updated(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=300)
        assert monitor.last_check == 0.0
        await monitor._check()
        assert monitor.last_check > 0.0

    async def test_exception_treated_as_unhealthy(self) -> None:
        check = AsyncMock()
        check.is_session_valid.side_effect = RuntimeError("network down")
        monitor = SessionHealthMonitor(check, interval=300)
        await monitor._check()
        assert monitor.is_healthy is False
        assert monitor._consecutive_failures == 1


class TestBackoffSchedule:
    def test_healthy_returns_default_interval(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=300)
        assert monitor._next_interval() == 300.0

    def test_first_failure_backoff(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=300)
        monitor._consecutive_failures = 1
        assert monitor._next_interval() == _BACKOFF_BASE_S  # 60

    def test_second_failure_doubles(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=300)
        monitor._consecutive_failures = 2
        assert monitor._next_interval() == _BACKOFF_BASE_S * 2  # 120

    def test_third_failure_quadruples(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=300)
        monitor._consecutive_failures = 3
        assert monitor._next_interval() == _BACKOFF_BASE_S * 4  # 240

    def test_backoff_capped(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=300)
        monitor._consecutive_failures = 100
        assert monitor._next_interval() == _BACKOFF_CAP_S  # 900


class TestStartStop:
    async def test_start_creates_task(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=300)
        monitor.start()
        assert monitor._task is not None
        assert not monitor._task.done()
        await monitor.stop()

    async def test_stop_cancels_task(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=300)
        monitor.start()
        await monitor.stop()
        assert monitor._task is None

    async def test_stop_when_not_started_is_noop(self, healthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(healthy_check, interval=300)
        await monitor.stop()  # should not raise


class TestConsecutiveFailures:
    async def test_multiple_failures_increment(self, unhealthy_check: AsyncMock) -> None:
        monitor = SessionHealthMonitor(unhealthy_check, interval=300)
        for _ in range(4):
            await monitor._check()
        assert monitor._consecutive_failures == 4
        assert monitor.is_healthy is False
