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

from sophia.domain.learning import EventPayloadValue, LearningEvent, LearningEventType

if TYPE_CHECKING:
    from collections.abc import Sequence

    import aiosqlite

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """How many events of a batch were newly recorded versus already known."""

    accepted: int
    duplicate: int


async def ingest_events(
    db: aiosqlite.Connection,
    events: Sequence[LearningEvent],
    *,
    max_future_skew_seconds: int,
) -> IngestionResult:
    """Record a batch of learner-process events idempotently."""
    received_at = datetime.now(UTC)
    latest_acceptable = received_at + timedelta(seconds=max_future_skew_seconds)

    accepted = 0
    for event in events:
        occurred_at = min(event.occurred_at, latest_acceptable)
        cursor = await db.execute(
            "INSERT INTO learning_events ("
            "event_id, course_id, user_id, event_type, occurred_at, received_at, "
            "session_id, question_id, payload) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(event_id) DO NOTHING",
            (
                event.event_id,
                event.course_id,
                event.user_id,
                event.event_type.value,
                occurred_at.isoformat(),
                received_at.isoformat(),
                event.session_id,
                event.question_id,
                json.dumps(event.payload, sort_keys=True),
            ),
        )
        accepted += cursor.rowcount if cursor.rowcount > 0 else 0
    await db.commit()

    duplicate = len(events) - accepted
    log.info("learning_events_ingested", accepted=accepted, duplicate=duplicate)
    return IngestionResult(accepted=accepted, duplicate=duplicate)


async def get_question_trace(
    db: aiosqlite.Connection,
    course_id: int,
    question_id: str,
    user_id: str,
) -> list[LearningEvent]:
    """Load one learner's recorded events for a single question, oldest first."""
    cursor = await db.execute(
        "SELECT event_id, course_id, user_id, event_type, occurred_at, session_id, "
        "question_id, payload FROM learning_events "
        "WHERE course_id = ? AND question_id = ? AND user_id = ? "
        "ORDER BY occurred_at",
        (course_id, question_id, user_id),
    )
    rows = cast("Sequence[tuple[object, ...]]", await cursor.fetchall())
    return [_row_to_event(row) for row in rows]


async def purge_expired_events(
    db: aiosqlite.Connection,
    *,
    retention_days: int,
) -> int:
    """Delete events past the retention window and return how many were removed.

    Process traces are evidence about a person's learning, so they are kept for
    a bounded window rather than indefinitely.
    """
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    cursor = await db.execute(
        "DELETE FROM learning_events WHERE received_at < ?",
        (cutoff.isoformat(),),
    )
    await db.commit()
    purged = max(cursor.rowcount, 0)
    log.info("learning_events_purged", purged=purged, retention_days=retention_days)
    return purged


def _row_to_event(row: tuple[object, ...]) -> LearningEvent:
    return LearningEvent(
        event_id=str(row[0]),
        course_id=int(cast("int", row[1])),
        user_id=str(row[2]),
        event_type=LearningEventType(str(row[3])),
        occurred_at=datetime.fromisoformat(str(row[4])),
        session_id=None if row[5] is None else int(cast("int", row[5])),
        question_id=None if row[6] is None else str(row[6]),
        payload=_decode_payload(row[7]),
    )


def _decode_payload(raw: object) -> dict[str, EventPayloadValue]:
    if not isinstance(raw, str) or not raw:
        return {}
    decoded = cast("object", json.loads(raw))
    if not isinstance(decoded, dict):
        return {}
    return cast("dict[str, EventPayloadValue]", decoded)
