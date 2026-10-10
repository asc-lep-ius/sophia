"""Nightly: scan for new recordings and queue every subscribed course (#128).

Runs inside the API, beside the session keepalive, because that is the one
long-lived process that holds a TU Wien session. The scan is the product's
own discovery; what it queues is only what a student has subscribed to, so
last semester's modules cost no GPU hours unless somebody asks.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import structlog

from sophia.services.hermes_catalog import discover_lecture_modules
from sophia.services.ingestion_jobs import enqueue_subscribed

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sophia.infra.di import AppContainer

log = structlog.get_logger()


def seconds_until(hour_utc: int, now: datetime) -> float:
    """How long to wait for the next occurrence of ``hour_utc`` after ``now``."""
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


class NightlyIngestion:
    def __init__(
        self,
        container: AppContainer,
        *,
        hour_utc: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._container = container
        self._hour_utc = hour_utc
        self._clock = clock
        self._sleep = sleep

    async def run(self) -> None:
        while True:
            await self._sleep(seconds_until(self._hour_utc, self._clock()))
            try:
                await self.tick()
            except Exception as exc:
                # The next night gets another chance; the reason is logged
                # without the traceback, whose frames may hold the session.
                log.error("nightly_ingestion.failed", error=type(exc).__name__, reason=str(exc))

    async def tick(self) -> list[int]:
        settings = self._container.settings
        async with self._container.session() as session:
            discovered = await discover_lecture_modules(self._container, session)
            queued = await enqueue_subscribed(
                session,
                requested_by="nightly",
                stale_after_s=settings.ingestion_worker_stale_seconds,
            )
        log.info("nightly_ingestion.ran", discovered=len(discovered), queued=queued)
        return queued
