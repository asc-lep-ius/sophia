"""The nightly scan that keeps subscribed courses processed (#128)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

from sophia.services import ingestion_schedule
from sophia.services.ingestion_schedule import NightlyIngestion, seconds_until

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.parametrize(
    ("now", "expected_seconds"),
    [
        (datetime(2026, 10, 10, 1, 30, tzinfo=UTC), 90 * 60),
        (datetime(2026, 10, 10, 3, 0, tzinfo=UTC), 24 * 3600),
        (datetime(2026, 10, 10, 22, 0, tzinfo=UTC), 5 * 3600),
    ],
)
def test_seconds_until_the_next_three_oclock(now: datetime, expected_seconds: int) -> None:
    assert seconds_until(3, now) == expected_seconds


async def test_a_tick_discovers_then_queues_the_subscribed_courses(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import contextlib

    @contextlib.asynccontextmanager
    async def _session(**_kwargs: object) -> AsyncIterator[AsyncSession]:
        yield db

    container = MagicMock()
    container.session = _session
    container.settings.ingestion_worker_stale_seconds = 90
    discover = AsyncMock(return_value=[object(), object()])
    enqueue = AsyncMock(return_value=[82774])
    monkeypatch.setattr(ingestion_schedule, "discover_lecture_modules", discover)
    monkeypatch.setattr(ingestion_schedule, "enqueue_subscribed", enqueue)

    queued = await NightlyIngestion(container, hour_utc=3).tick()

    assert queued == [82774]
    discover.assert_awaited_once_with(container, db)
    assert enqueue.await_args is not None
    assert enqueue.await_args.kwargs == {"requested_by": "nightly", "stale_after_s": 90}


async def test_the_loop_sleeps_until_the_hour_and_survives_a_failed_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    ticks = 0

    async def sleep(seconds: float) -> None:
        slept.append(seconds)
        if len(slept) == 3:
            raise StopAsyncIteration

    nightly = NightlyIngestion(
        MagicMock(),
        hour_utc=3,
        clock=lambda: datetime(2026, 10, 10, 1, 0, tzinfo=UTC),
        sleep=sleep,
    )

    async def failing_tick() -> list[int]:
        nonlocal ticks
        ticks += 1
        raise RuntimeError("TUWEL is down")

    monkeypatch.setattr(nightly, "tick", failing_tick)
    with pytest.raises(StopAsyncIteration):
        await nightly.run()

    assert slept == [7200.0, 7200.0, 7200.0]
    assert ticks == 2
