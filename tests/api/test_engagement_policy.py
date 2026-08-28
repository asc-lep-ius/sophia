"""Engagement policy enforcement: answers require a recorded learning process."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

import aiosqlite
import pytest

from sophia.api.sessions import SessionTenant
from sophia.domain.learning import (
    ContentLanguage,
    ElaborationPolicy,
    GeneratedQuestion,
    LearningEvent,
    LearningEventType,
    QuestionKind,
)
from sophia.infra.persistence import run_migrations
from sophia.services.engagement_policy import evaluate_elaboration_policy
from sophia.services.learning_events import ingest_events
from sophia.services.study_questions import ELABORATION_REQUIRED_EVENTS, _insert_question

from ._session_helpers import ApiHarness, build_harness, csrf_headers, login

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from httpx import Response

    from sophia.infra.di import AppContainer

QUESTION_ID = "question-1"
LEARNING_PATH_ID = 12
POLICY = ElaborationPolicy(
    required_event_types=ELABORATION_REQUIRED_EVENTS,
    min_elaboration_chars=80,
    min_prompt_dwell_ms=5000,
)


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: aiosqlite.Connection


@pytest.fixture
async def db() -> AsyncIterator[aiosqlite.Connection]:
    connection = await aiosqlite.connect(":memory:")
    await connection.execute("PRAGMA foreign_keys=ON")
    await run_migrations(connection)
    await _insert_question(
        connection,
        GeneratedQuestion(
            id=QUESTION_ID,
            course_id=LEARNING_PATH_ID,
            topic="Graphs",
            kind=QuestionKind.OPEN_RESPONSE,
            prompt="Why does a minimum cut bound maximum flow?",
            difficulty="explain",
            content_language=ContentLanguage.DE,
            elaboration_policy=POLICY,
        ),
    )
    await connection.commit()
    yield connection
    await connection.close()


def build_logged_in_harness(db: aiosqlite.Connection) -> ApiHarness:
    harness = build_harness(
        app_container=cast("AppContainer", FakeAppContainer(db=db)),
        tenant=SessionTenant(
            org_id="tu-wien",
            learning_path_id=str(LEARNING_PATH_ID),
            cohort_id="cohort-a",
            role="student",
        ),
    )
    login(harness, username="learner")
    return harness


def trace_event(
    event_id: str,
    event_type: LearningEventType,
    payload: dict[str, str | int | float | bool | None],
) -> LearningEvent:
    return LearningEvent(
        event_id=event_id,
        course_id=LEARNING_PATH_ID,
        user_id="learner",
        event_type=event_type,
        occurred_at=datetime.now(UTC),
        question_id=QUESTION_ID,
        payload=payload,
    )


async def record_complete_trace(db: aiosqlite.Connection) -> None:
    await ingest_events(
        db,
        [
            trace_event("event-1", LearningEventType.PROMPT_SHOWN, {"dwell_ms": 9000}),
            trace_event("event-2", LearningEventType.PREDICTION_MADE, {"confidence": 3}),
            trace_event("event-3", LearningEventType.ELABORATION_WRITTEN, {"text_length": 140}),
        ],
        max_future_skew_seconds=60,
    )


def submit_answer(
    harness: ApiHarness,
    answer: str = "A cut bounds flow because every unit crosses it.",
) -> Response:
    return harness.client.post(
        "/api/study/attempts",
        json={
            "learning_path_id": LEARNING_PATH_ID,
            "question_id": QUESTION_ID,
            "answer_text": answer,
            "confidence": 3,
        },
        headers=csrf_headers(harness),
    )


async def test_answer_without_trace_is_rejected_with_412(db: aiosqlite.Connection) -> None:
    harness = build_logged_in_harness(db)

    response = submit_answer(harness)

    assert response.status_code == 412
    assert response.json()["detail"]["code"] == "engagement.policy_unmet"
    cursor = await db.execute("SELECT COUNT(*) FROM question_attempts")
    assert await cursor.fetchone() == (0,)


async def test_rejection_names_the_missing_steps(db: aiosqlite.Connection) -> None:
    harness = build_logged_in_harness(db)

    params = submit_answer(harness).json()["detail"]["params"]

    assert params["missing_event_types"] == ("prompt_shown,prediction_made,elaboration_written")
    assert params["elaboration_chars"] == 0


async def test_answer_with_complete_trace_is_accepted(db: aiosqlite.Connection) -> None:
    harness = build_logged_in_harness(db)
    await record_complete_trace(db)

    response = submit_answer(harness)

    assert response.status_code == 200
    attempt = response.json()["attempt"]
    assert attempt["question_id"] == QUESTION_ID
    assert attempt["learning_path_id"] == LEARNING_PATH_ID


async def test_shallow_elaboration_does_not_satisfy_the_policy(db: aiosqlite.Connection) -> None:
    """Emitting the right event types is not enough; the work has to be there."""
    harness = build_logged_in_harness(db)
    await ingest_events(
        db,
        [
            trace_event("event-1", LearningEventType.PROMPT_SHOWN, {"dwell_ms": 9000}),
            trace_event("event-2", LearningEventType.PREDICTION_MADE, {}),
            trace_event("event-3", LearningEventType.ELABORATION_WRITTEN, {"text_length": 4}),
        ],
        max_future_skew_seconds=60,
    )

    response = submit_answer(harness)

    assert response.status_code == 412
    assert response.json()["detail"]["params"]["elaboration_chars"] == 4


async def test_another_learners_trace_does_not_unlock_the_question(
    db: aiosqlite.Connection,
) -> None:
    harness = build_logged_in_harness(db)
    await ingest_events(
        db,
        [
            LearningEvent(
                event_id=f"event-{index}",
                course_id=LEARNING_PATH_ID,
                user_id="somebody-else",
                event_type=event_type,
                occurred_at=datetime.now(UTC),
                question_id=QUESTION_ID,
                payload={"dwell_ms": 9000, "text_length": 140},
            )
            for index, event_type in enumerate(ELABORATION_REQUIRED_EVENTS)
        ],
        max_future_skew_seconds=60,
    )

    assert submit_answer(harness).status_code == 412


async def test_unknown_question_is_404(db: aiosqlite.Connection) -> None:
    harness = build_logged_in_harness(db)

    response = harness.client.post(
        "/api/study/attempts",
        json={
            "learning_path_id": LEARNING_PATH_ID,
            "question_id": "does-not-exist",
            "answer_text": "anything",
        },
        headers=csrf_headers(harness),
    )

    assert response.status_code == 404


def test_policy_evaluation_reports_every_missing_requirement() -> None:
    outcome = evaluate_elaboration_policy(POLICY, [])

    assert outcome.met is False
    assert outcome.missing_event_types == ELABORATION_REQUIRED_EVENTS
    assert outcome.prompt_dwell_ms == 0
