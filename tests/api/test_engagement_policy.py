"""Engagement policy enforcement: answers require a recorded learning process."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select

from sophia.domain.learning import (
    ContentLanguage,
    ElaborationPolicy,
    GeneratedQuestion,
    LearningEvent,
    LearningEventType,
    QuestionKind,
)
from sophia.infra.schema import confidence_ratings, question_attempts
from sophia.services.athena_session import start_study_session
from sophia.services.engagement_policy import evaluate_elaboration_policy
from sophia.services.learning_events import ingest_events
from sophia.services.study_questions import (
    ELABORATION_REQUIRED_EVENTS,
    SELF_RATING_SCORES,
    _insert_question,
)

from ._db_harness import db_harness, learning_path_tenant

if TYPE_CHECKING:
    from httpx import Response
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from ._db_harness import DbHarness

pytestmark = pytest.mark.postgres

QUESTION_ID = "question-1"
LEARNING_PATH_ID = 12
POLICY = ElaborationPolicy(
    required_event_types=ELABORATION_REQUIRED_EVENTS,
    min_elaboration_chars=80,
    min_prompt_dwell_ms=5000,
)


async def seed_session(session: AsyncSession, *, user_id: str = "learner") -> int:
    study_session = await start_study_session(session, LEARNING_PATH_ID, "Graphs", user_id=user_id)
    return study_session.id


async def seed_question(session: AsyncSession) -> None:
    await _insert_question(
        session,
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


def trace_event(
    event_id: str,
    event_type: LearningEventType,
    payload: dict[str, str | int | float | bool | None],
    *,
    user_id: str = "learner",
) -> LearningEvent:
    return LearningEvent(
        event_id=event_id,
        course_id=LEARNING_PATH_ID,
        user_id=user_id,
        event_type=event_type,
        occurred_at=datetime.now(UTC),
        question_id=QUESTION_ID,
        payload=payload,
    )


# Spelled out because a bare dict literal infers dict[str, int], and dict is
# invariant, so it would not satisfy trace_event's wider payload type.
type TracePayload = dict[str, str | int | float | bool | None]
COMPLETE_TRACE: tuple[tuple[str, LearningEventType, TracePayload], ...] = (
    ("event-1", LearningEventType.PROMPT_SHOWN, {"dwell_ms": 9000}),
    ("event-2", LearningEventType.PREDICTION_MADE, {"confidence": 3}),
    ("event-3", LearningEventType.ELABORATION_WRITTEN, {"text_length": 140}),
)


async def submit_answer(
    harness: DbHarness,
    answer: str = "A cut bounds flow because every unit crosses it.",
    *,
    session_id: int,
    self_rating: int = 3,
    request_id: str = "req-1",
) -> Response:
    return await harness.client.post(
        "/api/study/attempts",
        json={
            "learning_path_id": LEARNING_PATH_ID,
            "session_id": session_id,
            "question_id": QUESTION_ID,
            "answer_text": answer,
            "confidence": 3,
            "self_rating": self_rating,
            "request_id": request_id,
        },
        headers=harness.csrf_headers(),
    )


async def attempt_count(harness: DbHarness) -> int:
    async with harness.seed() as session:
        return await session.scalar(select(func.count()).select_from(question_attempts)) or 0


async def test_answer_without_trace_is_rejected_with_412(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session)
            session_id = await seed_session(session)
        await harness.login()

        response = await submit_answer(harness, session_id=session_id)
        stored = await attempt_count(harness)

    assert response.status_code == 412
    assert response.json()["detail"]["code"] == "engagement.policy_unmet"
    assert stored == 0


async def test_rejection_names_the_missing_steps(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session)
            session_id = await seed_session(session)
        await harness.login()

        params = (await submit_answer(harness, session_id=session_id)).json()["detail"]["params"]

    assert params["missing_event_types"] == "prompt_shown,prediction_made,elaboration_written"
    assert params["elaboration_chars"] == 0


async def test_answer_with_complete_trace_is_accepted(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session)
            session_id = await seed_session(session)
            await ingest_events(
                session,
                [trace_event(*event) for event in COMPLETE_TRACE],
                max_future_skew_seconds=60,
            )
        await harness.login()

        response = await submit_answer(harness, session_id=session_id, self_rating=3)

    assert response.status_code == 200
    attempt = response.json()["attempt"]
    assert attempt["question_id"] == QUESTION_ID
    assert attempt["learning_path_id"] == LEARNING_PATH_ID
    assert attempt["score"] == pytest.approx(0.7)


async def test_shallow_elaboration_does_not_satisfy_the_policy(
    clean_engine: AsyncEngine,
) -> None:
    """Emitting the right event types is not enough; the work has to be there."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session)
            session_id = await seed_session(session)
            await ingest_events(
                session,
                [
                    trace_event("event-1", LearningEventType.PROMPT_SHOWN, {"dwell_ms": 9000}),
                    trace_event("event-2", LearningEventType.PREDICTION_MADE, {}),
                    trace_event(
                        "event-3", LearningEventType.ELABORATION_WRITTEN, {"text_length": 4}
                    ),
                ],
                max_future_skew_seconds=60,
            )
        await harness.login()

        response = await submit_answer(harness, session_id=session_id)

    assert response.status_code == 412
    assert response.json()["detail"]["params"]["elaboration_chars"] == 4


async def test_another_learners_trace_does_not_unlock_the_question(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session)
            session_id = await seed_session(session)
            await ingest_events(
                session,
                [
                    trace_event(event_id, event_type, payload, user_id="somebody-else")
                    for event_id, event_type, payload in COMPLETE_TRACE
                ],
                max_future_skew_seconds=60,
            )
        await harness.login()

        response = await submit_answer(harness, session_id=session_id)

    assert response.status_code == 412


async def test_unknown_question_is_404(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        await harness.login()

        response = await harness.client.post(
            "/api/study/attempts",
            json={
                "learning_path_id": LEARNING_PATH_ID,
                "session_id": 1,
                "question_id": "does-not-exist",
                "answer_text": "anything",
                "self_rating": 3,
                "request_id": "req-1",
            },
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 404


def test_policy_evaluation_reports_every_missing_requirement() -> None:
    outcome = evaluate_elaboration_policy(POLICY, [])

    assert outcome.met is False
    assert outcome.missing_event_types == ELABORATION_REQUIRED_EVENTS
    assert outcome.prompt_dwell_ms == 0


async def test_duplicate_attempt_request_id_is_idempotent(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session)
            session_id = await seed_session(session)
            await ingest_events(
                session,
                [trace_event(*event) for event in COMPLETE_TRACE],
                max_future_skew_seconds=60,
            )
        await harness.login()

        first = await submit_answer(harness, session_id=session_id, request_id="dup-1")
        retry = await submit_answer(harness, session_id=session_id, request_id="dup-1")
        stored = await attempt_count(harness)

    assert first.status_code == 200
    assert retry.status_code == 200
    assert first.json() == retry.json()
    assert stored == 1


async def test_attempt_rejects_a_session_owned_by_another_learner(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session)
            session_id = await seed_session(session, user_id="somebody-else")
        await harness.login("learner")

        response = await submit_answer(harness, session_id=session_id)
        stored = await attempt_count(harness)

    assert response.status_code == 404
    assert stored == 0


async def test_attempt_score_reaches_only_the_grading_learners_own_prediction(
    clean_engine: AsyncEngine,
) -> None:
    """A graded attempt must update the submitting learner's own most-recent
    prediction for the topic, never another learner's — confidence_ratings has
    no per-session key, only (topic, course_id, user_id)."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session)
            session_id = await seed_session(session)
            await ingest_events(
                session,
                [trace_event(*event) for event in COMPLETE_TRACE],
                max_future_skew_seconds=60,
            )
        await harness.login("learner")

        # Two learners each predict the same topic before either is graded.
        own_prediction = await harness.client.post(
            "/api/study/predictions",
            json={
                "learning_path_id": LEARNING_PATH_ID,
                "session_id": session_id,
                "topic": "Graphs",
                "rating": 4,
                "request_id": "pred-learner",
            },
            headers=harness.csrf_headers(),
        )
        assert own_prediction.status_code == 200

        async with harness.seed() as session:
            other_session_id = await seed_session(session, user_id="other-learner")
            await session.execute(
                confidence_ratings.insert().values(
                    topic="Graphs",
                    course_id=LEARNING_PATH_ID,
                    predicted=0.5,
                    session_id=other_session_id,
                    user_id="other-learner",
                    request_id="pred-other",
                )
            )

        response = await submit_answer(harness, session_id=session_id, self_rating=1)
        assert response.status_code == 200

        async with harness.seed() as session:
            rows = (
                await session.execute(
                    select(
                        confidence_ratings.c.user_id,
                        confidence_ratings.c.actual,
                    ).where(confidence_ratings.c.topic == "Graphs")
                )
            ).all()

    by_user = {row.user_id: row.actual for row in rows}
    assert by_user["learner"] == pytest.approx(SELF_RATING_SCORES[1])
    assert by_user["other-learner"] is None
