"""Engagement policy enforcement: answers require a recorded learning process."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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
    default_elaboration_policy,
)

from ._db_harness import db_harness, learning_path_tenant

if TYPE_CHECKING:
    from httpx import Response
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from ._db_harness import DbHarness

pytestmark = pytest.mark.postgres

QUESTION_ID = "question-1"
ANCHOR_ID = "anchor-question"
LEARNING_PATH_ID = 12
POLICY = ElaborationPolicy(
    required_event_types=ELABORATION_REQUIRED_EVENTS,
    min_elaboration_chars=80,
    min_prompt_dwell_ms=5000,
)


async def seed_session(session: AsyncSession, *, user_id: str = "learner") -> int:
    study_session = await start_study_session(session, LEARNING_PATH_ID, "Graphs", user_id=user_id)
    return study_session.id


async def seed_question(
    session: AsyncSession,
    question_id: str = QUESTION_ID,
    *,
    session_id: int | None = None,
    policy: ElaborationPolicy = POLICY,
) -> None:
    await _insert_question(
        session,
        GeneratedQuestion(
            id=question_id,
            course_id=LEARNING_PATH_ID,
            topic="Graphs",
            kind=QuestionKind.OPEN_RESPONSE,
            prompt="Why does a minimum cut bound maximum flow?",
            difficulty="explain",
            content_language=ContentLanguage.DE,
            elaboration_policy=policy,
            session_id=session_id,
        ),
    )


def trace_event(
    event_id: str,
    event_type: LearningEventType,
    payload: dict[str, str | int | float | bool | None],
    *,
    user_id: str = "learner",
    question_id: str = QUESTION_ID,
    session_id: int | None = None,
    occurred_at: datetime | None = None,
) -> LearningEvent:
    return LearningEvent(
        event_id=event_id,
        course_id=LEARNING_PATH_ID,
        user_id=user_id,
        event_type=event_type,
        occurred_at=occurred_at or datetime.now(UTC),
        session_id=session_id,
        question_id=question_id,
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
    question_id: str = QUESTION_ID,
    phase: str = "practice",
) -> Response:
    return await harness.client.post(
        "/api/study/attempts",
        json={
            "learning_path_id": LEARNING_PATH_ID,
            "session_id": session_id,
            "question_id": question_id,
            "answer_text": answer,
            "confidence": 3,
            "self_rating": self_rating,
            "request_id": request_id,
            "phase": phase,
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


# --- prediction_made is per session (#107) ---------------------------------
#
# The learner predicts once, on /predict against the session's anchor question,
# and that prediction covers every card worked on /act. The rest of the trace
# stays per question.

PROMPT_DWELLED: TracePayload = {"dwell_ms": 9000}
ELABORATED: TracePayload = {"text_length": 140}
CARD_TRACE: tuple[tuple[str, LearningEventType, TracePayload], ...] = (
    ("event-1", LearningEventType.PROMPT_SHOWN, PROMPT_DWELLED),
    ("event-2", LearningEventType.ELABORATION_WRITTEN, ELABORATED),
)


def anchor_prediction(session_id: int, *, user_id: str = "learner") -> LearningEvent:
    return trace_event(
        "event-anchor-prediction",
        LearningEventType.PREDICTION_MADE,
        {"rating": 3},
        user_id=user_id,
        question_id=ANCHOR_ID,
        session_id=session_id,
    )


async def test_the_sessions_prediction_covers_a_card_it_was_not_made_on(
    clean_engine: AsyncEngine,
) -> None:
    """Every /act card used to be refused: only the anchor carried a prediction."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session)
            session_id = await seed_session(session)
            await ingest_events(
                session,
                [*(trace_event(*event) for event in CARD_TRACE), anchor_prediction(session_id)],
                max_future_skew_seconds=60,
            )
        await harness.login()

        response = await submit_answer(harness, session_id=session_id)

    assert response.status_code == 200, response.json()


async def test_a_session_without_a_prediction_refuses_every_card(
    clean_engine: AsyncEngine,
) -> None:
    """Per session is not optional: a card's own trace does not stand in for it."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session)
            session_id = await seed_session(session)
            await ingest_events(
                session,
                [trace_event(*event) for event in CARD_TRACE],
                max_future_skew_seconds=60,
            )
        await harness.login()

        response = await submit_answer(harness, session_id=session_id)
        stored = await attempt_count(harness)

    assert response.status_code == 412
    assert response.json()["detail"]["code"] == "engagement.policy_unmet"
    assert response.json()["detail"]["params"]["missing_event_types"] == "prediction_made"
    assert stored == 0


async def test_a_prediction_in_another_session_does_not_cover_this_one(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session)
            session_id = await seed_session(session)
            earlier_session_id = await seed_session(session)
            await ingest_events(
                session,
                [
                    *(trace_event(*event) for event in CARD_TRACE),
                    anchor_prediction(earlier_session_id),
                ],
                max_future_skew_seconds=60,
            )
        await harness.login()

        response = await submit_answer(harness, session_id=session_id)

    assert response.status_code == 412
    assert response.json()["detail"]["params"]["missing_event_types"] == "prediction_made"


async def test_another_learners_prediction_does_not_cover_the_session(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session)
            session_id = await seed_session(session)
            await ingest_events(
                session,
                [
                    *(trace_event(*event) for event in CARD_TRACE),
                    anchor_prediction(session_id, user_id="somebody-else"),
                ],
                max_future_skew_seconds=60,
            )
        await harness.login()

        response = await submit_answer(harness, session_id=session_id)

    assert response.status_code == 412


def test_only_the_prediction_carries_across_the_session() -> None:
    """Another card's prompt and elaboration are that card's work, not this one's."""
    session_events = [
        trace_event("event-1", LearningEventType.PROMPT_SHOWN, PROMPT_DWELLED),
        trace_event("event-2", LearningEventType.PREDICTION_MADE, {"rating": 3}),
        trace_event("event-3", LearningEventType.ELABORATION_WRITTEN, ELABORATED),
    ]

    outcome = evaluate_elaboration_policy(POLICY, [], session_events)

    assert outcome.missing_event_types == (
        LearningEventType.PROMPT_SHOWN,
        LearningEventType.ELABORATION_WRITTEN,
    )
    assert outcome.elaboration_chars == 0
    assert outcome.prompt_dwell_ms == 0


async def post_events(
    harness: DbHarness,
    session_id: int,
    question_id: str,
    *events: tuple[str, TracePayload],
) -> None:
    """Record a card's trace the way the study surface does: through the API."""
    response = await harness.client.post(
        "/api/events/batch",
        json={
            "learning_path_id": LEARNING_PATH_ID,
            "events": [
                {
                    "event_id": f"{question_id}-{event_type}",
                    "event_type": event_type,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "session_id": session_id,
                    "question_id": question_id,
                    "payload": payload,
                }
                for event_type, payload in events
            ],
        },
        headers=harness.csrf_headers(),
    )
    assert response.status_code == 200, response.json()


async def test_a_deck_drains_end_to_end_under_the_generated_policy(
    clean_engine: AsyncEngine,
) -> None:
    """The acceptance for #107, against the real policy check rather than the
    e2e fixture, which accepts every attempt and so could never have caught it.

    Predict once on the anchor, answer it as the pre-test, then work every
    remaining card with only its own prompt and elaboration recorded.
    """
    policy = default_elaboration_policy(min_elaboration_chars=80, min_prompt_dwell_ms=5000)
    cards = ["card-1", "card-2", "card-3"]

    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
            for question_id in [ANCHOR_ID, *cards]:
                await seed_question(session, question_id, session_id=session_id, policy=policy)
        await harness.login()

        await post_events(
            harness,
            session_id,
            ANCHOR_ID,
            ("prompt_shown", PROMPT_DWELLED),
            ("prediction_made", {"rating": 3}),
            ("elaboration_written", ELABORATED),
        )
        pre_test = await submit_answer(
            harness,
            session_id=session_id,
            question_id=ANCHOR_ID,
            phase="pre_test",
            request_id="req-anchor",
        )
        practice = []
        for question_id in cards:
            await post_events(
                harness,
                session_id,
                question_id,
                ("prompt_shown", PROMPT_DWELLED),
                ("elaboration_written", ELABORATED),
            )
            practice.append(
                await submit_answer(
                    harness,
                    session_id=session_id,
                    question_id=question_id,
                    request_id=f"req-{question_id}",
                )
            )

        async with harness.seed() as session:
            answered = set(
                (
                    await session.scalars(
                        select(question_attempts.c.question_id).where(
                            question_attempts.c.session_id == session_id,
                            question_attempts.c.user_id == "learner",
                        )
                    )
                ).all()
            )

    assert pre_test.status_code == 200, pre_test.json()
    assert [response.status_code for response in practice] == [200, 200, 200]
    assert answered == {ANCHOR_ID, *cards}


# --- the prediction comes before the reveal (#169) ---------------------------
#
# A prediction made with the material in view is the inflated judgement the
# predict step exists to expose (Koriat & Bjork 2005), so an attempt whose
# answer was revealed before the session's prediction is refused like any other
# missing step, when it lands.

PREDICTED_AT = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)


def pre_test_trace(
    *, revealed_at: datetime, session_id: int | None = 7, reveal_session_id: int | None = 7
) -> list[LearningEvent]:
    return [
        trace_event("event-1", LearningEventType.PROMPT_SHOWN, PROMPT_DWELLED),
        trace_event("event-2", LearningEventType.ELABORATION_WRITTEN, ELABORATED),
        trace_event(
            "event-3",
            LearningEventType.ANSWER_REVEALED,
            {},
            session_id=reveal_session_id,
            occurred_at=revealed_at,
        ),
        trace_event(
            "event-4",
            LearningEventType.PREDICTION_MADE,
            {"rating": 4},
            session_id=session_id,
            occurred_at=PREDICTED_AT,
        ),
    ]


def test_a_reveal_before_the_prediction_does_not_meet_the_policy() -> None:
    trace = pre_test_trace(revealed_at=PREDICTED_AT - timedelta(seconds=30))

    outcome = evaluate_elaboration_policy(POLICY, trace, session_id=7)

    assert outcome.met is False
    assert outcome.missing_event_types == ()
    assert outcome.revealed_before_prediction is True
    assert outcome.params["revealed_before_prediction"] is True


def test_a_reveal_after_the_prediction_meets_the_policy() -> None:
    trace = pre_test_trace(revealed_at=PREDICTED_AT + timedelta(seconds=30))

    outcome = evaluate_elaboration_policy(POLICY, trace, session_id=7)

    assert outcome.met is True
    assert outcome.revealed_before_prediction is False


@pytest.mark.parametrize(
    ("second_prediction_offset", "met"),
    [
        pytest.param(timedelta(minutes=-5), True, id="predicted-before-the-reveal-too"),
        pytest.param(timedelta(minutes=5), False, id="rating-changed-after-the-reveal"),
    ],
)
def test_the_reveal_is_measured_against_the_first_prediction(
    second_prediction_offset: timedelta,
    met: bool,
) -> None:
    """Changing the rating after a reveal does not make the reveal any less early."""
    trace = [
        *pre_test_trace(revealed_at=PREDICTED_AT - timedelta(seconds=30)),
        trace_event(
            "event-5",
            LearningEventType.PREDICTION_MADE,
            {"rating": 2},
            session_id=7,
            occurred_at=PREDICTED_AT + second_prediction_offset,
        ),
    ]

    outcome = evaluate_elaboration_policy(POLICY, trace, session_id=7)

    assert outcome.met is met


def test_a_reveal_in_another_session_is_not_held_against_this_one() -> None:
    trace = pre_test_trace(
        revealed_at=PREDICTED_AT - timedelta(days=3),
        reveal_session_id=3,
    )

    outcome = evaluate_elaboration_policy(POLICY, trace, session_id=7)

    assert outcome.revealed_before_prediction is False


@pytest.mark.parametrize(
    ("reveal_offset", "expected_status"),
    [
        pytest.param(timedelta(seconds=-20), 412, id="revealed-first"),
        pytest.param(timedelta(seconds=20), 200, id="predicted-first"),
    ],
)
async def test_an_attempt_revealed_before_the_sessions_prediction_is_refused(
    clean_engine: AsyncEngine,
    reveal_offset: timedelta,
    expected_status: int,
) -> None:
    """The pre-test card used to be revealable before the rating: the server took
    the grade once a prediction existed, however late it came."""
    policy = default_elaboration_policy(min_elaboration_chars=80, min_prompt_dwell_ms=5000)
    predicted_at = datetime.now(UTC) - timedelta(minutes=1)
    revealed_at = predicted_at + reveal_offset

    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
            await seed_question(session, ANCHOR_ID, session_id=session_id, policy=policy)
        await harness.login()

        events = [
            ("prompt_shown", PROMPT_DWELLED, revealed_at - timedelta(seconds=10)),
            ("elaboration_written", ELABORATED, revealed_at - timedelta(seconds=5)),
            ("answer_revealed", {}, revealed_at),
            ("prediction_made", {"rating": 4}, predicted_at),
        ]
        ingested = await harness.client.post(
            "/api/events/batch",
            json={
                "learning_path_id": LEARNING_PATH_ID,
                "events": [
                    {
                        "event_id": f"{ANCHOR_ID}-{event_type}",
                        "event_type": event_type,
                        "occurred_at": at.isoformat(),
                        "session_id": session_id,
                        "question_id": ANCHOR_ID,
                        "payload": payload,
                    }
                    for event_type, payload, at in events
                ],
            },
            headers=harness.csrf_headers(),
        )
        assert ingested.status_code == 200, ingested.json()

        response = await submit_answer(
            harness,
            session_id=session_id,
            question_id=ANCHOR_ID,
            phase="pre_test",
        )
        stored = await attempt_count(harness)

    assert response.status_code == expected_status, response.json()
    if expected_status == 412:
        detail = response.json()["detail"]
        assert detail["code"] == "engagement.policy_unmet"
        assert detail["params"]["revealed_before_prediction"] is True
        assert detail["params"]["missing_event_types"] == ""
        assert stored == 0
    else:
        assert stored == 1
