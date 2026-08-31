"""Learning event ingestion, retention, and forgery-resistance tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select, update

from sophia.domain.learning import LearningEvent, LearningEventType
from sophia.infra.schema import learning_events
from sophia.services.learning_events import (
    get_question_trace,
    ingest_events,
    purge_expired_events,
)

from ._db_harness import db_harness, learning_path_tenant

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.postgres


def event_body(event_id: str, event_type: str = "prompt_shown") -> dict[str, object]:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2026-05-26T14:00:00Z",
        "question_id": "question-1",
        "payload": {"dwell_ms": 9000},
    }


async def test_batch_ingestion_is_idempotent_per_event_id(clean_engine: AsyncEngine) -> None:
    body = {"learning_path_id": 12, "events": [event_body("event-1"), event_body("event-2")]}

    async with db_harness(clean_engine) as harness:
        await harness.login()
        first = await harness.client.post(
            "/api/events/batch", json=body, headers=harness.csrf_headers()
        )
        retry = await harness.client.post(
            "/api/events/batch", json=body, headers=harness.csrf_headers()
        )

    assert first.status_code == 200
    assert first.json() == {"learning_path_id": 12, "accepted": 2, "duplicate": 0}
    assert retry.json() == {"learning_path_id": 12, "accepted": 0, "duplicate": 2}


async def test_ingestion_attributes_events_to_the_session_user(
    clean_engine: AsyncEngine,
) -> None:
    """A client cannot file events under somebody else's name."""
    async with db_harness(clean_engine) as harness:
        await harness.login("learner-a")
        response = await harness.client.post(
            "/api/events/batch",
            json={
                "learning_path_id": 12,
                "events": [{**event_body("event-1"), "user_id": "somebody-else"}],
            },
            headers=harness.csrf_headers(),
        )
        async with harness.seed() as session:
            owner = await session.scalar(
                select(learning_events.c.user_id).where(
                    learning_events.c.event_id == "event-1",
                )
            )

    assert response.status_code == 200
    assert owner == "learner-a"


async def test_ingestion_rejects_out_of_scope_learning_paths(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(12)) as harness:
        await harness.login()
        response = await harness.client.post(
            "/api/events/batch",
            json={"learning_path_id": 99, "events": [event_body("event-1")]},
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 403


async def test_ingestion_requires_authentication(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine) as harness:
        response = await harness.client.post(
            "/api/events/batch",
            json={"learning_path_id": 12, "events": [event_body("event-1")]},
            headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
        )

    assert response.status_code == 401


async def test_oversized_batches_are_rejected(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine) as harness:
        await harness.login()
        response = await harness.client.post(
            "/api/events/batch",
            json={
                "learning_path_id": 12,
                "events": [event_body(f"event-{index}") for index in range(101)],
            },
            headers=harness.csrf_headers(),
        )
        async with harness.seed() as session:
            stored = await session.scalar(select(func.count()).select_from(learning_events))

    assert response.status_code == 422
    assert stored == 0


async def test_future_timestamps_are_clamped_to_arrival(db: AsyncSession) -> None:
    """A postdated event cannot be used to claim work that has not happened."""
    far_future = datetime.now(UTC) + timedelta(days=30)
    await ingest_events(
        db,
        [
            LearningEvent(
                event_id="event-1",
                course_id=12,
                user_id="learner",
                event_type=LearningEventType.PROMPT_SHOWN,
                occurred_at=far_future,
                question_id="question-1",
            )
        ],
        max_future_skew_seconds=60,
    )

    trace = await get_question_trace(db, 12, "question-1", "learner")

    assert len(trace) == 1
    assert trace[0].occurred_at < far_future


async def test_expired_events_are_purged(db: AsyncSession) -> None:
    await ingest_events(
        db,
        [
            LearningEvent(
                event_id="event-1",
                course_id=12,
                user_id="learner",
                event_type=LearningEventType.PROMPT_SHOWN,
                occurred_at=datetime.now(UTC),
                question_id="question-1",
            )
        ],
        max_future_skew_seconds=60,
    )
    await db.execute(
        update(learning_events)
        .where(learning_events.c.event_id == "event-1")
        .values(received_at=datetime.now(UTC) - timedelta(days=400))
    )

    purged = await purge_expired_events(db, retention_days=180)

    assert purged == 1
    assert await get_question_trace(db, 12, "question-1", "learner") == []
