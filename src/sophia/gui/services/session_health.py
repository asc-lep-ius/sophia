"""Session health monitoring with keepalive and exponential backoff."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from sophia.domain.ports import SessionHealthCheck

log = structlog.get_logger()

_BACKOFF_BASE_S = 60
_BACKOFF_CAP_S = 900


class SessionHealthMonitor:
    """Periodic session health check with exponential backoff on failure.

    Runs as an asyncio background task. On failure, backs off exponentially
    from 60s up to a cap of 900s. On recovery, resets to the default interval.
    State is exposed via ``is_healthy`` and ``last_check`` for GUI consumption.
    """

    def __init__(self, health_check: SessionHealthCheck, interval: int = 300) -> None:
        self._health_check = health_check
        self._default_interval = interval
        self._healthy = True
        self._consecutive_failures = 0
        self._task: asyncio.Task[None] | None = None
        self._last_check: float = 0.0

    def start(self) -> None:
        """Start the background keepalive loop."""
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        """Cancel the background keepalive loop."""
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def last_check(self) -> float:
        return self._last_check

    def _next_interval(self) -> float:
        if self._consecutive_failures == 0:
            return float(self._default_interval)
        return min(
            _BACKOFF_BASE_S * (2 ** (self._consecutive_failures - 1)),
            _BACKOFF_CAP_S,
        )

    async def _loop(self) -> None:
        """Run health checks forever, sleeping between them."""
        while True:
            await self._check()
            await asyncio.sleep(self._next_interval())

    async def _check(self) -> None:
        """Ping session health and log state transitions."""
        try:
            valid = await self._health_check.is_session_valid()
        except Exception:
            valid = False

        self._last_check = time.monotonic()

        if valid and not self._healthy:
            log.info("session_health_transition", from_state="unhealthy", to_state="healthy")
        elif not valid and self._healthy:
            log.warning("session_health_transition", from_state="healthy", to_state="unhealthy")

        if valid:
            self._healthy = True
            self._consecutive_failures = 0
        else:
            self._healthy = False
            self._consecutive_failures += 1
