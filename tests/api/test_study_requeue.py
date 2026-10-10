"""A card graded Again comes back later in the same session (#170).

Driven through the real routers rather than the e2e fixture: what is under test
is what the server stores for a retry, what it averages, and what it tells a
resumed session it still owes — and the fixture has no scoring of its own to
be wrong about.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, update

from sophia.domain.learning import (
    ContentKind,
    ContentLanguage,
    ContentProvenance,
    GeneratedQuestion,
    ProvenanceAgent,
    QuestionKind,
    StoredContentOrigin,
)
from sophia.infra.schema import question_attempts, study_sessions
from sophia.services.athena_session import save_reflection, start_study_session
from sophia.services.provenance import record_provenance
from sophia.services.study_questions import (
    AGAIN_REASK_LIMIT,
    _insert_question,
    default_elaboration_policy,
)

from ._db_harness import db_harness, learning_path_tenant

if TYPE_CHECKING:
    from httpx import Response
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from ._db_harness import DbHarness

pytestmark = pytest.mark.postgres

LEARNING_PATH_ID = 12
TOPIC = "Graphs"
ANCHOR = "anchor"
CARDS = ("card-1", "card-2", "card-3", "card-4")
# save_attempt maps Again/Hard/Good/Easy onto 0.0/0.3/0.7/1.0.
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
ANSWER = "A cut bounds flow because every unit of flow from s to t has to cross it exactly once."

type Payload = dict[str, str | int | float | bool | None]


async def seed_session(session: AsyncSession) -> int:
    """An anchor and four practice cards, under the policy the generator issues."""
    study_session = await start_study_session(session, LEARNING_PATH_ID, TOPIC, user_id="learner")
    policy = default_elaboration_policy(min_elaboration_chars=80, min_prompt_dwell_ms=5000)
    for question_id in (ANCHOR, *CARDS):
        await _insert_question(
            session,
            GeneratedQuestion(
                id=question_id,
                course_id=LEARNING_PATH_ID,
                topic=TOPIC,
                kind=QuestionKind.OPEN_RESPONSE,
                prompt=f"Explain {question_id}.",
                difficulty="explain",
                content_language=ContentLanguage.EN,
                elaboration_policy=policy,
                session_id=study_session.id,
            ),
        )
        # The deck endpoint refuses to serve a question it cannot attribute.
        await record_provenance(
            session,
            ContentProvenance(
                content_kind=ContentKind.QUESTION,
                content_id=question_id,
                course_id=LEARNING_PATH_ID,
                origin=StoredContentOrigin.TUWEL,
                generated_by=ProvenanceAgent.MODEL,
                generator_ref="test-generator",
                generated_at="2026-09-04T10:00:00+00:00",
            ),
        )
    return study_session.id


@dataclass
class Learner:
    """Works cards through the API the way the study surface does.

    Every presentation records its own trace under fresh event ids, and every
    grade mints a fresh request id: a re-ask is a new attempt, not a resend.
    """

    harness: DbHarness
    session_id: int

    def __post_init__(self) -> None:
        self._ids = count(1)
        self.last_request: dict[str, object] = {}

    async def predict(self) -> None:
        await self._events(ANCHOR, ("prediction_made", {"rating": 3}))

    async def answer(self, question_id: str, self_rating: int, *, phase: str = "practice") -> int:
        """Grade one presentation of a card; returns the stored attempt's id."""
        await self._events(
            question_id,
            ("prompt_shown", {"dwell_ms": 9000}),
            ("elaboration_written", {"text_length": len(ANSWER)}),
        )
        self.last_request = {
            "learning_path_id": LEARNING_PATH_ID,
            "session_id": self.session_id,
            "question_id": question_id,
            "answer_text": ANSWER,
            "confidence": 3,
            "self_rating": self_rating,
            "request_id": f"req-{next(self._ids)}",
            "phase": phase,
        }
        response = await self._post_attempt(self.last_request)
        assert response.status_code == 200, response.json()
        return int(response.json()["attempt"]["id"])

    async def resend_last(self, **changes: object) -> Response:
        """The outbox resending a grade it never saw the answer to."""
        return await self._post_attempt({**self.last_request, **changes})

    async def owed(self) -> list[tuple[str, int]]:
        """What a resumed session reads back as still to be asked again."""
        response = await self.harness.client.get(f"/api/study/sessions/{self.session_id}/questions")
        assert response.status_code == 200, response.json()
        return [
            (entry["question_id"], entry["attempts"])
            for entry in response.json()["requeued_questions"]
        ]

    async def _post_attempt(self, body: dict[str, object]) -> Response:
        return await self.harness.client.post(
            "/api/study/attempts", json=body, headers=self.harness.csrf_headers()
        )

    async def _events(self, question_id: str, *events: tuple[str, Payload]) -> None:
        response = await self.harness.client.post(
            "/api/events/batch",
            json={
                "learning_path_id": LEARNING_PATH_ID,
                "events": [
                    {
                        "event_id": f"event-{next(self._ids)}",
                        "event_type": event_type,
                        "occurred_at": datetime.now(UTC).isoformat(),
                        "session_id": self.session_id,
                        "question_id": question_id,
                        "payload": payload,
                    }
                    for event_type, payload in events
                ],
            },
            headers=self.harness.csrf_headers(),
        )
        assert response.status_code == 200, response.json()


async def on_work(harness: DbHarness, session_id: int) -> Learner:
    """Signed in, predicted and past the pre-test: on Work with four cards."""
    await harness.login()
    learner = Learner(harness, session_id)
    await learner.predict()
    await learner.answer(ANCHOR, GOOD, phase="pre_test")
    return learner


async def test_a_retry_is_stored_as_its_own_attempt(clean_engine: AsyncEngine) -> None:
    """The re-ask is a second row under its own request id, and resending that
    request id still folds into the row it made rather than adding a third."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
        learner = await on_work(harness, session_id)

        first = await learner.answer("card-2", AGAIN)
        retry = await learner.answer("card-2", GOOD)
        resent = await learner.resend_last(self_rating=EASY)

        async with harness.seed() as session:
            ratings = (
                await session.scalars(
                    select(question_attempts.c.self_rating)
                    .where(question_attempts.c.question_id == "card-2")
                    .order_by(question_attempts.c.id)
                )
            ).all()

    assert first != retry
    assert resent.status_code == 200
    assert resent.json()["attempt"]["id"] == retry
    assert resent.json()["attempt"]["self_rating"] == GOOD
    assert ratings == [AGAIN, GOOD]


async def test_practice_mean_uses_each_questions_last_attempt(clean_engine: AsyncEngine) -> None:
    """Good on one card, Again then Good on another: 0.7, where averaging all
    three attempts would have reported 0.47."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
        learner = await on_work(harness, session_id)

        await learner.answer("card-1", GOOD)
        await learner.answer("card-2", AGAIN)
        await learner.answer("card-2", GOOD)
        response = await harness.client.get(f"/api/study/sessions/{session_id}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["practice_score"] == pytest.approx(0.7)
    assert body["measured"] == pytest.approx(0.7)
    # Every attempt is still on record; only the mean reads the last one.
    assert body["attempts"]["practice"] == 3


async def test_completion_scores_each_phase_from_its_last_attempts(
    clean_engine: AsyncEngine,
) -> None:
    """The measured score of a completed session is its post-test mean, and a
    post-test question answered twice counts once, as the later answer."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
        learner = await on_work(harness, session_id)
        await learner.answer(ANCHOR, AGAIN, phase="post_test")
        await learner.answer(ANCHOR, EASY, phase="post_test")
        async with harness.seed() as session:
            await save_reflection(
                session,
                session_id,
                LEARNING_PATH_ID,
                "learner",
                "Which part still feels unfinished?",
                "The cut argument took me a while.",
                request_id="refl-1",
            )
            # Completion refuses a reflection inside the pacing floor.
            await session.execute(
                update(study_sessions)
                .where(study_sessions.c.id == session_id)
                .values(started_at=datetime.now(UTC) - timedelta(minutes=5))
            )

        completed = await harness.client.post(
            f"/api/study/sessions/{session_id}/complete", headers=harness.csrf_headers()
        )
        summary = await harness.client.get(f"/api/study/sessions/{session_id}/summary")

    assert completed.status_code == 200, completed.json()
    assert completed.json()["session"]["pre_test_score"] == pytest.approx(0.7)
    assert completed.json()["session"]["post_test_score"] == pytest.approx(1.0)
    assert summary.json()["measured"] == pytest.approx(1.0)


async def test_a_resumed_session_still_owes_the_card_graded_again(
    clean_engine: AsyncEngine,
) -> None:
    """The tab closes between the Again and the re-ask: the deck read back on
    resume names the card, in the order the Agains were given."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
        learner = await on_work(harness, session_id)

        await learner.answer("card-1", GOOD)
        await learner.answer("card-3", AGAIN)
        await learner.answer("card-2", AGAIN)
        owed_before_retry = await learner.owed()
        await learner.answer("card-3", HARD)
        owed_after_retry = await learner.owed()

    assert owed_before_retry == [("card-3", 1), ("card-2", 1)]
    assert owed_after_retry == [("card-2", 1)]


async def test_a_card_stops_coming_back_once_the_cap_is_reached(
    clean_engine: AsyncEngine,
) -> None:
    """Presented at most twice more: the hardest card must not eat the session."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
        learner = await on_work(harness, session_id)

        owed = []
        for _presentation in range(AGAIN_REASK_LIMIT + 1):
            await learner.answer("card-2", AGAIN)
            owed.append(await learner.owed())

    assert AGAIN_REASK_LIMIT == 2
    assert owed == [[("card-2", 1)], [("card-2", 2)], []]


async def test_an_again_on_the_pre_test_is_not_owed_a_re_ask(clean_engine: AsyncEngine) -> None:
    """The pre-test is a measurement: its Again is the result, not a card to practise."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
        await harness.login()
        learner = Learner(harness, session_id)
        await learner.predict()
        await learner.answer(ANCHOR, AGAIN, phase="pre_test")

        owed = await learner.owed()

    assert owed == []
