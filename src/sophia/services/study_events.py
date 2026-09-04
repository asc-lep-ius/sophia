"""The durable, replayable study-session event log the SSE endpoint reads from.

Every row here is written in the same transaction as the domain effect it
describes (an attempt scored, a prediction recorded, ...), so durability and
"this happened" are the same commit — there is no window where a write
succeeded but the event that should announce it did not, or vice versa.

``pg_notify`` is fired in the same statement batch purely as a low-latency
wake-up hint for open SSE connections; nothing about correctness depends on a
listener actually receiving it — a connection that misses the notification
still sees the event on its next heartbeat-driven catch-up read, because the
event log, not the notification, is what the SSE endpoint replays.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import structlog
from sqlalchemy import delete, func, select, text

from sophia.infra.engine import affected_rows
from sophia.infra.schema import study_events

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

NOTIFY_CHANNEL = "study_events"

_NOTIFY_SQL = text("SELECT pg_notify(:channel, :payload)")


@dataclass(frozen=True, slots=True)
class StudyEventRow:
    """A replayed event, shaped for direct SSE-frame rendering."""

    id: int
    event_type: str
    payload: dict[str, object]
    server_time: str


async def append_event(
    session: AsyncSession,
    *,
    session_id: int,
    course_id: int,
    actor_id: str,
    event_type: str,
    payload: Mapping[str, object],
    request_id: str | None = None,
    client_time: datetime | None = None,
) -> int:
    """Append one event and wake any listening SSE connections. Returns its id."""
    event_id = (
        await session.execute(
            study_events.insert()
            .values(
                session_id=session_id,
                course_id=course_id,
                actor_id=actor_id,
                event_type=event_type,
                payload=dict(payload),
                request_id=request_id,
                client_time=client_time,
            )
            .returning(study_events.c.id)
        )
    ).scalar_one()

    await session.execute(
        _NOTIFY_SQL,
        {
            "channel": NOTIFY_CHANNEL,
            "payload": json.dumps({"session_id": session_id, "id": event_id}),
        },
    )
    return event_id


async def replay_events(
    session: AsyncSession,
    *,
    session_id: int,
    after_id: int,
    limit: int,
) -> list[StudyEventRow]:
    """Bounded, ordered read of events newer than ``after_id`` for one session."""
    rows = (
        await session.execute(
            select(study_events)
            .where(study_events.c.session_id == session_id, study_events.c.id > after_id)
            .order_by(study_events.c.id)
            .limit(limit)
        )
    ).all()
    return [_row_to_event(row) for row in rows]


async def oldest_retained_event_id(session: AsyncSession, *, session_id: int) -> int | None:
    """The lowest event id still retained for a session, or ``None`` if it has none."""
    return await session.scalar(
        select(func.min(study_events.c.id)).where(study_events.c.session_id == session_id)
    )


async def purge_expired_events(session: AsyncSession, *, retention_days: int) -> int:
    """Delete events past the retention window and return how many were removed."""
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await session.execute(delete(study_events).where(study_events.c.server_time < cutoff))
    purged = affected_rows(result)
    log.info("study_events_purged", purged=purged, retention_days=retention_days)
    return purged


def _row_to_event(row: Row[tuple[object, ...]]) -> StudyEventRow:
    payload = cast("object", row.payload)
    return StudyEventRow(
        id=row.id,
        event_type=row.event_type,
        payload=cast("dict[str, object]", payload) if isinstance(payload, dict) else {},
        server_time=row.server_time.isoformat() if row.server_time else "",
    )
