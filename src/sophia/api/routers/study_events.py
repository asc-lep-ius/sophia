"""Study realtime SSE endpoint.

``GET /study/{session_id}/events`` streams the durable ``study_events`` log for
one session. Cookie-only auth (native ``EventSource`` cannot set custom
headers, so this cannot require the CSRF header the mutating endpoints do —
GET is not a mutation). Postgres ``LISTEN``/``NOTIFY`` wakes an open
connection with low latency, but every wake re-reads the event log rather than
trusting the notification payload: a missed ``NOTIFY`` (a dropped listener
connection, a burst that outran the queue) still self-heals on the next
heartbeat-driven catch-up read, so correctness never depends on delivery.

This deliberately does not use ``request_session`` — see the docstring on
``TransactionalRoute`` for why a streaming route must not: the request's
transaction stack closes when the handler returns, before the body generator
ever runs. Every database access here opens its own short-lived session
through the app container instead.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Annotated

import anyio
import asyncpg  # pyright: ignore[reportMissingTypeStubs]
import structlog
from fastapi import APIRouter, HTTPException, Path, Request, status
from starlette.responses import StreamingResponse

from sophia.api.context import get_request_context
from sophia.api.deps import current_session_record, get_app_container, get_settings
from sophia.api.routers.metrics import SSE_CONNECTIONS_OPEN, SSE_DISCONNECTS, SSE_EVENTS_EMITTED
from sophia.api.transactions import TransactionalRoute
from sophia.infra.engine import asyncpg_dsn
from sophia.infra.org_context import DEFAULT_ORG_ID
from sophia.services.athena_session import get_session_scope
from sophia.services.study_events import (
    NOTIFY_CHANNEL,
    StudyEventRow,
    oldest_retained_event_id,
    replay_events,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sophia.config import Settings
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

STREAM_NAME = "study"
_STREAM_SLOT_KEY_PREFIX = "sse:study:streams"
_CLEANUP_TIMEOUT_SECONDS = 5
"""Bound on the shielded finally-block cleanup — not settings-driven like the
other timings in this module, since it's an internal safety cap against a
wedged Postgres/Redis call, not something an operator would tune per
deployment."""

router = APIRouter(tags=["study"], route_class=TransactionalRoute)

SessionIdPath = Annotated[int, Path(gt=0)]


@router.get("/study/{session_id}/events", include_in_schema=False)
async def stream_study_events(session_id: SessionIdPath, request: Request) -> StreamingResponse:
    settings = get_settings(request)
    app_container = get_app_container(request)
    auth_session = await current_session_record(request)

    context = get_request_context()
    org_id = context.org_id if context is not None else DEFAULT_ORG_ID
    async with app_container.session(org_id=org_id) as db:
        scope = await get_session_scope(db, session_id)
    if scope is None or scope.user_id != auth_session.user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if not await _reserve_stream_slot(request, auth_session.user.id, settings):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    return StreamingResponse(
        _event_stream(
            app_container,
            request,
            session_id=session_id,
            user_id=auth_session.user.id,
            org_id=org_id,
            settings=settings,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


async def _event_stream(
    app_container: AppContainer,
    request: Request,
    *,
    session_id: int,
    user_id: str,
    org_id: str,
    settings: Settings,
) -> AsyncGenerator[str]:
    SSE_CONNECTIONS_OPEN.labels(stream=STREAM_NAME).inc()
    disconnect_reason = "server_shutdown"
    last_id = _initial_last_event_id(request)
    queue: asyncio.Queue[None] = asyncio.Queue(maxsize=settings.sse_queue_maxsize)
    overflowed = False

    def _on_notify(_conn: object, _pid: int, _channel: str, payload: str) -> None:
        # The payload names the session an event belongs to; a stream that
        # ignores it wakes for every event in the deployment, not just its
        # own. Any parse failure falls through to waking anyway — a spurious
        # wake costs one DB read, but ignoring one that mattered would not
        # self-heal until the next heartbeat.
        nonlocal overflowed
        with contextlib.suppress(ValueError, TypeError, KeyError):
            if json.loads(payload)["session_id"] != session_id:
                return
        try:
            queue.put_nowait(None)
        except asyncio.QueueFull:
            overflowed = True

    # asyncpg ships no inline type annotations, so its whole surface resolves
    # to Unknown under strict mode — ignored here rather than case by case.
    listener_conn = None  # pyright: ignore[reportUnknownVariableType]
    try:
        listener_conn = await asyncpg.connect(  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
            asyncpg_dsn(app_container.settings.database_url)
        )
        await listener_conn.add_listener(  # pyright: ignore[reportUnknownMemberType]
            NOTIFY_CHANNEL, _on_notify
        )

        gap = await _gap_event_if_needed(app_container, session_id, last_id, org_id=org_id)
        if gap is not None:
            yield gap
            SSE_EVENTS_EMITTED.labels(stream=STREAM_NAME, event_type="gap").inc()

        while True:
            if await request.is_disconnected():
                disconnect_reason = "client"
                return

            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(queue.get(), timeout=settings.sse_heartbeat_interval_seconds)

            if overflowed:
                disconnect_reason = "overflow"
                return

            await _renew_stream_slot(request, user_id, settings)

            async with app_container.session(org_id=org_id) as db:
                events = await replay_events(
                    db,
                    session_id=session_id,
                    after_id=last_id,
                    limit=settings.sse_replay_batch_size,
                )

            if not events:
                yield "event: heartbeat\ndata: {}\n\n"
                SSE_EVENTS_EMITTED.labels(stream=STREAM_NAME, event_type="heartbeat").inc()
                continue

            for event in events:
                last_id = event.id
                yield _sse_frame(event)
                SSE_EVENTS_EMITTED.labels(stream=STREAM_NAME, event_type=event.event_type).inc()
    except asyncio.CancelledError:
        disconnect_reason = "client"
        raise
    finally:
        # A client disconnect cancels this generator inside a cancel scope
        # that keeps re-delivering CancelledError to the first await it sees,
        # which would otherwise skip everything below the first `await` in
        # this block. The metric calls are sync (safe either way); the
        # cleanup awaits are shielded so cancellation cannot skip them —
        # an unshielded `finally` here was observed to leave the connections
        # gauge growing monotonically and the Redis slot never released.
        SSE_CONNECTIONS_OPEN.labels(stream=STREAM_NAME).dec()
        SSE_DISCONNECTS.labels(stream=STREAM_NAME, reason=disconnect_reason).inc()
        # Bounded even though shielded: an unresponsive Postgres or Redis
        # must not pin this response task open indefinitely just because
        # cancellation can no longer reach it.
        with anyio.move_on_after(_CLEANUP_TIMEOUT_SECONDS, shield=True):
            if listener_conn is not None:
                with contextlib.suppress(Exception):
                    await listener_conn.close()  # pyright: ignore[reportUnknownMemberType]
            await _release_stream_slot(request, user_id)


def _initial_last_event_id(request: Request) -> int:
    raw = request.headers.get("last-event-id")
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


async def _gap_event_if_needed(
    app_container: AppContainer,
    session_id: int,
    last_id: int,
    *,
    org_id: str,
) -> str | None:
    """Explicit reset when a reconnect asks for an id retention already dropped."""
    if last_id <= 0:
        return None
    async with app_container.session(org_id=org_id) as db:
        oldest = await oldest_retained_event_id(db, session_id=session_id)
    if oldest is not None and oldest > last_id:
        return 'event: gap\ndata: {"reason":"retention"}\n\n'
    return None


def _sse_frame(event: StudyEventRow) -> str:
    data = json.dumps(event.payload, separators=(",", ":"), sort_keys=True)
    return f"id: {event.id}\nevent: {event.event_type}\ndata: {data}\n\n"


async def _reserve_stream_slot(request: Request, user_id: str, settings: Settings) -> bool:
    """Best-effort per-user concurrent-stream cap via the app's Redis client.

    Redis (not an in-process counter) is what keeps this correct with multiple
    Uvicorn workers. When no distributed Redis client is configured — tests
    that inject a session_core directly, bypassing app.py's own Redis wiring —
    there is nothing to count against, so the check is skipped rather than
    failing closed.
    """
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return True
    key = _stream_slot_key(user_id)
    current = await redis_client.incr(key)
    await redis_client.expire(key, _stream_slot_ttl_seconds(settings))
    if current > settings.sse_max_streams_per_user:
        await redis_client.decr(key)
        return False
    return True


async def _renew_stream_slot(request: Request, user_id: str, settings: Settings) -> None:
    """Refresh the slot key's TTL so a long-lived stream doesn't outlive it.

    Without this a stream open longer than the TTL has its slot silently
    expire, and the next connection undercounts how many are actually open.
    """
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    with contextlib.suppress(Exception):
        await redis_client.expire(_stream_slot_key(user_id), _stream_slot_ttl_seconds(settings))


async def _release_stream_slot(request: Request, user_id: str) -> None:
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    with contextlib.suppress(Exception):
        key = _stream_slot_key(user_id)
        remaining = await redis_client.decr(key)
        # A slot leaked by a crash that never released it (or a TTL expiry
        # racing a release) can drive the counter negative; DECR sets no TTL
        # of its own, so a stray negative key would otherwise persist and
        # loosen the cap for every future connection. Deleting rather than
        # resetting to 0 leaves nothing behind — a missing key INCRs to 1 the
        # same way a 0 key would. Best-effort: a concurrent reserve/release
        # can still race it, matching the rest of this cap's best-effort
        # nature.
        if remaining < 0:
            await redis_client.delete(key)


def _stream_slot_key(user_id: str) -> str:
    return f"{_STREAM_SLOT_KEY_PREFIX}:{user_id}"


def _stream_slot_ttl_seconds(settings: Settings) -> int:
    return settings.sse_heartbeat_interval_seconds * 4
