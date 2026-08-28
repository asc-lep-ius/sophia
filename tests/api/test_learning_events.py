"""Learning event ingestion, retention, and forgery-resistance tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, cast

import aiosqlite
import pytest

from sophia.api.sessions import SessionTenant
from sophia.domain.learning import LearningEvent, LearningEventType
from sophia.infra.persistence import run_migrations
from sophia.services.learning_events import (
    get_question_trace,
    ingest_events,
    purge_expired_events,
)

from ._session_helpers import build_harness, csrf_headers, login

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sophia.infra.di import AppContainer


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: aiosqlite.Connection


@pytest.fixture
async def db() -> AsyncIterator[aiosqlite.Connection]:
    connection = await aiosqlite.connect(":memory:")
    await connection.execute("PRAGMA foreign_keys=ON")
    await run_migrations(connection)
    yield connection
    await connection.close()


def learning_path_tenant(learning_path_id: int = 12) -> SessionTenant:
    return SessionTenant(
        org_id="tu-wien",
        learning_path_id=str(learning_path_id),
        cohort_id="cohort-a",
        role="student",
    )


def event_body(event_id: str, event_type: str = "prompt_shown") -> dict[str, object]:
    return {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2026-05-26T14:00:00Z",
        "question_id": "question-1",
        "payload": {"dwell_ms": 9000},
    }


async def test_batch_ingestion_is_idempotent_per_event_id(db: aiosqlite.Connection) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=db)),
        tenant=learning_path_tenant(),
    )
    login(harness)
    body = {"learning_path_id": 12, "events": [event_body("event-1"), event_body("event-2")]}

    first = harness.client.post("/api/events/batch", json=body, headers=csrf_headers(harness))
    retry = harness.client.post("/api/events/batch", json=body, headers=csrf_headers(harness))

    assert first.status_code == 200
    assert first.json() == {"learning_path_id": 12, "accepted": 2, "duplicate": 0}
    assert retry.json() == {"learning_path_id": 12, "accepted": 0, "duplicate": 2}


async def test_ingestion_attributes_events_to_the_session_user(db: aiosqlite.Connection) -> None:
    """A client cannot file events under somebody else's name."""
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=db)),
        tenant=learning_path_tenant(),
    )
    login(harness, username="learner-a")

    response = harness.client.post(
        "/api/events/batch",
        json={
            "learning_path_id": 12,
            "events": [{**event_body("event-1"), "user_id": "somebody-else"}],
        },
        headers=csrf_headers(harness),
    )

    assert response.status_code == 200
    cursor = await db.execute("SELECT user_id FROM learning_events WHERE event_id = 'event-1'")
    assert await cursor.fetchone() == ("learner-a",)


async def test_ingestion_rejects_out_of_scope_learning_paths(db: aiosqlite.Connection) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=db)),
        tenant=learning_path_tenant(12),
    )
    login(harness)

    response = harness.client.post(
        "/api/events/batch",
        json={"learning_path_id": 99, "events": [event_body("event-1")]},
        headers=csrf_headers(harness),
    )

    assert response.status_code == 403


def test_ingestion_requires_authentication() -> None:
    harness = build_harness(
        app_container=cast(
            "AppContainer", FakeAppContainer(db=cast("aiosqlite.Connection", object()))
        )
    )

    response = harness.client.post(
        "/api/events/batch",
        json={"learning_path_id": 12, "events": [event_body("event-1")]},
        headers={"X-Requested-With": "fetch", "X-CSRF-Token": "missing-session"},
    )

    assert response.status_code == 401


async def test_oversized_batches_are_rejected(db: aiosqlite.Connection) -> None:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=db)),
        tenant=learning_path_tenant(),
    )
    login(harness)

    response = harness.client.post(
        "/api/events/batch",
        json={
            "learning_path_id": 12,
            "events": [event_body(f"event-{index}") for index in range(101)],
        },
        headers=csrf_headers(harness),
    )

    assert response.status_code == 422
    cursor = await db.execute("SELECT COUNT(*) FROM learning_events")
    assert await cursor.fetchone() == (0,)


async def test_future_timestamps_are_clamped_to_arrival(db: aiosqlite.Connection) -> None:
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


async def test_expired_events_are_purged(db: aiosqlite.Connection) -> None:
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
        "UPDATE learning_events SET received_at = ? WHERE event_id = 'event-1'",
        ((datetime.now(UTC) - timedelta(days=400)).isoformat(),),
    )
    await db.commit()

    purged = await purge_expired_events(db, retention_days=180)

    assert purged == 1
    assert await get_question_trace(db, 12, "question-1", "learner") == []
