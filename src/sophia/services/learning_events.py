"""Learning event ingestion — the trace that engagement policy is judged against.

Events are the only evidence the server has that a learner did the cognitive
work, so ingestion is deliberately defensive: batches are bounded by the request
schema, the owning user and learning path come from the session rather than the
body, ``event_id`` makes a retried batch idempotent, and an ``occurred_at`` in
the future is clamped to arrival time so a client cannot backdate or postdate
its way past a policy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.domain.learning import EventPayloadValue, LearningEvent, LearningEventType
from sophia.infra.engine import affected_rows
from sophia.infra.schema import learning_events

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """How many events of a batch were newly recorded versus already known."""

    accepted: int
    duplicate: int


async def ingest_events(
    session: AsyncSession,
    events: Sequence[LearningEvent],
    *,
    max_future_skew_seconds: int,
) -> IngestionResult:
    """Record a batch of learner-process events idempotently."""
    if not events:
        return IngestionResult(accepted=0, duplicate=0)

    received_at = datetime.now(UTC)
    latest_acceptable = received_at + timedelta(seconds=max_future_skew_seconds)

    statement = pg_insert(learning_events).values(
        [
            {
                "event_id": event.event_id,
                "course_id": event.course_id,
                "user_id": event.user_id,
                "event_type": event.event_type.value,
                "occurred_at": min(event.occurred_at, latest_acceptable),
                "received_at": received_at,
                "session_id": event.session_id,
                "question_id": event.question_id,
                "payload": json.dumps(event.payload, sort_keys=True),
            }
            for event in events
        ]
    )
    result = await session.execute(
        statement.on_conflict_do_nothing(index_elements=[learning_events.c.event_id]).returning(
            learning_events.c.event_id,
        )
    )
    accepted = len(result.all())
    duplicate = len(events) - accepted
    log.info("learning_events_ingested", accepted=accepted, duplicate=duplicate)
    return IngestionResult(accepted=accepted, duplicate=duplicate)


async def get_question_trace(
    session: AsyncSession,
    course_id: int,
    question_id: str,
    user_id: str,
) -> list[LearningEvent]:
    """Load one learner's recorded events for a single question, oldest first."""
    rows = (
        await session.execute(
            select(learning_events)
            .where(
                learning_events.c.course_id == course_id,
                learning_events.c.question_id == question_id,
                learning_events.c.user_id == user_id,
            )
            .order_by(learning_events.c.occurred_at)
        )
    ).all()
    return [_row_to_event(row) for row in rows]


async def purge_expired_events(
    session: AsyncSession,
    *,
    retention_days: int,
) -> int:
    """Delete events past the retention window and return how many were removed.

    Process traces are evidence about a person's learning, so they are kept for
    a bounded window rather than indefinitely.
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = await session.execute(
        delete(learning_events).where(learning_events.c.received_at < cutoff)
    )
    purged = affected_rows(result)
    log.info("learning_events_purged", purged=purged, retention_days=retention_days)
    return purged


async def count_events(session: AsyncSession, course_id: int) -> int:
    """Count recorded events for a learning path."""
    total = await session.scalar(
        select(func.count())
        .select_from(learning_events)
        .where(learning_events.c.course_id == course_id)
    )
    return total or 0


def _row_to_event(row: Row[tuple[object, ...]]) -> LearningEvent:
    return LearningEvent(
        event_id=row.event_id,
        course_id=row.course_id,
        user_id=row.user_id,
        event_type=LearningEventType(row.event_type),
        occurred_at=row.occurred_at,
        session_id=row.session_id,
        question_id=row.question_id,
        payload=_decode_payload(row.payload),
    )


def _decode_payload(raw: object) -> dict[str, EventPayloadValue]:
    if not isinstance(raw, str) or not raw:
        return {}
    decoded = cast("object", json.loads(raw))
    if not isinstance(decoded, dict):
        return {}
    return cast("dict[str, EventPayloadValue]", decoded)
