"""Study realtime SSE endpoint: auth/ownership at the HTTP layer, and
heartbeat/push/replay/gap behavior on the streaming generator directly.

httpx's ASGI transport (used elsewhere in this test suite specifically to keep
asyncpg on the test's own event loop — see _db_harness.py) awaits the whole
ASGI application call before a `client.stream()` response becomes readable, so
it cannot consume a genuinely open-ended SSE body incrementally: the endpoint
under test never terminates on its own by design. The generator
(`study_events._event_stream`) is exercised directly instead, against the same
real database the HTTP-layer tests use, with is_disconnected() standing in for
the client closing the connection.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest

from sophia.api.routers.study_events import _event_stream
from sophia.services.athena_session import start_study_session
from sophia.services.study_events import append_event

from ._db_harness import db_harness, learning_path_tenant

if TYPE_CHECKING:
    from fastapi import Request
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from sophia.infra.di import AppContainer

pytestmark = pytest.mark.postgres

LEARNING_PATH_ID = 12
_FAST_SETTINGS = {
    "sse_heartbeat_interval_seconds": 1,
    "sse_queue_maxsize": 4,
}


class _FakeAppState:
    redis = None


class _FakeApp:
    state = _FakeAppState()


class FakeSSERequest:
    """Stands in for the FastAPI Request the generator reads: reconnect
    headers, whether the client is still there, and app.state.redis (None
    here, same as a real app built without a distributed Redis client)."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}
        self.app = _FakeApp()
        self._disconnected = False

    async def is_disconnected(self) -> bool:
        return self._disconnected

    def disconnect(self) -> None:
        self._disconnected = True


async def seed_session(session: AsyncSession, *, user_id: str = "learner") -> int:
    study_session = await start_study_session(session, LEARNING_PATH_ID, "Graphs", user_id=user_id)
    return study_session.id


async def collect_until(
    agen: object,
    marker: str,
    *,
    timeout: float = 5.0,
) -> str:
    """Drain an SSE generator until a frame containing ``marker`` is seen."""

    async def _drain() -> str:
        buffer = ""
        async for frame in agen:  # type: ignore[attr-defined]
            buffer += frame
            if marker in buffer:
                return buffer
        return buffer

    return await asyncio.wait_for(_drain(), timeout=timeout)


async def test_stream_rejects_a_session_owned_by_another_learner(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, user_id="somebody-else")
        await harness.login("learner")

        response = await harness.client.get(f"/api/study/{session_id}/events")

    assert response.status_code == 404


async def test_stream_rejects_a_legacy_session_with_no_owner(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            legacy_session = await start_study_session(session, LEARNING_PATH_ID, "Graphs")
        await harness.login()

        response = await harness.client.get(f"/api/study/{legacy_session.id}/events")

    assert response.status_code == 404


async def test_stream_rejects_an_unauthenticated_caller(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)

        response = await harness.client.get(f"/api/study/{session_id}/events")

    assert response.status_code in (401, 403)


async def test_generator_emits_heartbeat_and_reports_metrics(clean_engine: AsyncEngine) -> None:
    async with db_harness(
        clean_engine,
        tenant=learning_path_tenant(LEARNING_PATH_ID),
        settings_overrides=_FAST_SETTINGS,
    ) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)

        request = FakeSSERequest()
        agen = _event_stream(
            cast("AppContainer", harness.container),
            cast("Request", request),
            session_id=session_id,
            user_id="learner",
            org_id="tu-wien",
            settings=harness.settings,
        )
        body = await collect_until(agen, "event: heartbeat")
        request.disconnect()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(agen.__anext__(), timeout=5.0)

    assert "event: heartbeat" in body


async def test_generator_delivers_a_pushed_event_before_the_heartbeat(
    clean_engine: AsyncEngine,
) -> None:
    """Proves NOTIFY-driven push, not just heartbeat-interval polling: the
    heartbeat is set far longer than the event actually takes to arrive."""
    async with db_harness(
        clean_engine,
        tenant=learning_path_tenant(LEARNING_PATH_ID),
        settings_overrides={"sse_heartbeat_interval_seconds": 30, "sse_queue_maxsize": 4},
    ) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)

        request = FakeSSERequest()
        agen = _event_stream(
            cast("AppContainer", harness.container),
            cast("Request", request),
            session_id=session_id,
            user_id="learner",
            org_id="tu-wien",
            settings=harness.settings,
        )

        async def push_soon() -> None:
            await asyncio.sleep(0.3)
            async with harness.seed() as session:
                await append_event(
                    session,
                    session_id=session_id,
                    course_id=LEARNING_PATH_ID,
                    actor_id="learner",
                    event_type="card_pushed",
                    payload={"card_id": "c1"},
                )

        pusher = asyncio.create_task(push_soon())
        body = await collect_until(agen, "event: card_pushed", timeout=10)
        await pusher
        request.disconnect()
        await agen.aclose()

    assert "event: card_pushed" in body
    assert '"card_id":"c1"' in body


async def test_generator_replays_only_events_after_last_event_id(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(
        clean_engine,
        tenant=learning_path_tenant(LEARNING_PATH_ID),
        settings_overrides=_FAST_SETTINGS,
    ) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
            first_id = await append_event(
                session,
                session_id=session_id,
                course_id=LEARNING_PATH_ID,
                actor_id="learner",
                event_type="first_event",
                payload={},
            )
            await append_event(
                session,
                session_id=session_id,
                course_id=LEARNING_PATH_ID,
                actor_id="learner",
                event_type="second_event",
                payload={},
            )

        request = FakeSSERequest(headers={"last-event-id": str(first_id)})
        agen = _event_stream(
            cast("AppContainer", harness.container),
            cast("Request", request),
            session_id=session_id,
            user_id="learner",
            org_id="tu-wien",
            settings=harness.settings,
        )
        body = await collect_until(agen, "event: second_event")
        request.disconnect()
        await agen.aclose()

    assert "event: second_event" in body
    assert "event: first_event" not in body


async def test_generator_reports_a_gap_outside_the_retention_window(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(
        clean_engine,
        tenant=learning_path_tenant(LEARNING_PATH_ID),
        settings_overrides=_FAST_SETTINGS,
    ) as harness:
        async with harness.seed() as session:
            # A dummy event in another session advances the global id sequence,
            # so the id it gets is guaranteed older than anything retained for
            # *this* session below — a stand-in for "purged by retention"
            # without needing to actually wait out or fake a retention window.
            other_session_id = await seed_session(session, user_id="other")
            stale_id = await append_event(
                session,
                session_id=other_session_id,
                course_id=LEARNING_PATH_ID,
                actor_id="other",
                event_type="dummy",
                payload={},
            )
            session_id = await seed_session(session)
            await append_event(
                session,
                session_id=session_id,
                course_id=LEARNING_PATH_ID,
                actor_id="learner",
                event_type="only_event",
                payload={},
            )

        request = FakeSSERequest(headers={"last-event-id": str(stale_id)})
        agen = _event_stream(
            cast("AppContainer", harness.container),
            cast("Request", request),
            session_id=session_id,
            user_id="learner",
            org_id="tu-wien",
            settings=harness.settings,
        )
        body = await collect_until(agen, "event: gap")
        request.disconnect()
        await agen.aclose()

    assert "event: gap" in body


async def test_generator_disconnect_increments_the_disconnect_metric(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(
        clean_engine,
        tenant=learning_path_tenant(LEARNING_PATH_ID),
        settings_overrides=_FAST_SETTINGS,
    ) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)

        before = await harness.client.get("/api/metrics")

        request = FakeSSERequest()
        agen = _event_stream(
            cast("AppContainer", harness.container),
            cast("Request", request),
            session_id=session_id,
            user_id="learner",
            org_id="tu-wien",
            settings=harness.settings,
        )
        await collect_until(agen, "event: heartbeat")
        request.disconnect()
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(agen.__anext__(), timeout=5.0)

        after = await harness.client.get("/api/metrics")

    before_count = _counter_value(
        before.text, 'sse_disconnect_total{reason="client",stream="study"}'
    )
    after_count = _counter_value(after.text, 'sse_disconnect_total{reason="client",stream="study"}')
    assert after_count == before_count + 1


def _counter_value(metrics_text: str, series: str) -> float:
    for line in metrics_text.splitlines():
        if line.startswith(series):
            return float(line.rsplit(" ", 1)[-1])
    return 0.0
