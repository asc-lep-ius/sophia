"""Server-side session scoring: phased attempts, completion, and the summary.

These run against a real Postgres because what is under test is the aggregation
itself — which attempts are averaged into which phase — not the plumbing around
it. A fake session would answer whatever the test taught it to.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import update

from sophia.domain.learning import (
    AttemptPhase,
    ContentKind,
    ContentLanguage,
    ContentProvenance,
    ElaborationPolicy,
    GeneratedQuestion,
    LearningEventType,
    ProvenanceAgent,
    QuestionKind,
    StoredContentOrigin,
)
from sophia.infra.schema import study_sessions
from sophia.services.athena_confidence import record_study_prediction
from sophia.services.athena_session import save_reflection, start_study_session
from sophia.services.provenance import record_provenance
from sophia.services.study_questions import _insert_question, save_attempt

from ._db_harness import db_harness, learning_path_tenant

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.postgres

LEARNING_PATH_ID = 12
TOPIC = "Graphs"
# save_attempt maps Again/Hard/Good/Easy onto 0.0/0.3/0.7/1.0.
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4


async def seed_session(session: AsyncSession, *, user_id: str = "learner") -> int:
    study_session = await start_study_session(session, LEARNING_PATH_ID, TOPIC, user_id=user_id)
    return study_session.id


async def seed_reflection(
    session: AsyncSession,
    session_id: int,
    *,
    user_id: str = "learner",
    seconds_after_start: int = 60,
) -> None:
    """Record a reflection, backdating the session so the pacing floor is met.

    Completion refuses a session whose reflection landed inside the floor, so a
    test that wants to reach the scoring path has to have paced like a learner.
    """
    await save_reflection(
        session,
        session_id,
        LEARNING_PATH_ID,
        user_id,
        "Which part still feels unfinished?",
        "The cut argument took me a while.",
        request_id=f"refl-{session_id}",
    )
    await session.execute(
        update(study_sessions)
        .where(study_sessions.c.id == session_id)
        .values(started_at=datetime.now(UTC) - timedelta(seconds=seconds_after_start))
    )


async def seed_question(
    session: AsyncSession,
    question_id: str,
    *,
    session_id: int | None = None,
) -> GeneratedQuestion:
    """Insert a question directly: generation itself needs a model provider."""
    question = GeneratedQuestion(
        id=question_id,
        course_id=LEARNING_PATH_ID,
        topic=TOPIC,
        kind=QuestionKind.OPEN_RESPONSE,
        prompt=f"Explain {question_id}.",
        difficulty="explain",
        content_language=ContentLanguage.EN,
        elaboration_policy=ElaborationPolicy(
            required_event_types=(LearningEventType.PROMPT_SHOWN,),
            min_elaboration_chars=0,
            min_prompt_dwell_ms=0,
        ),
        session_id=session_id,
    )
    await _insert_question(session, question)
    await record_provenance(
        session,
        ContentProvenance(
            content_kind=ContentKind.QUESTION,
            content_id=question.id,
            course_id=LEARNING_PATH_ID,
            origin=StoredContentOrigin.TUWEL,
            generated_by=ProvenanceAgent.MODEL,
            generator_ref="test-generator",
            generated_at="2026-09-04T10:00:00+00:00",
        ),
    )
    return question


async def seed_attempt(
    session: AsyncSession,
    session_id: int,
    question_id: str,
    *,
    self_rating: int,
    phase: AttemptPhase,
    request_id: str,
    user_id: str = "learner",
) -> None:
    await save_attempt(
        session,
        LEARNING_PATH_ID,
        question_id,
        user_id,
        "An answer long enough to count as elaboration.",
        4,
        session_id=session_id,
        request_id=request_id,
        self_rating=self_rating,
        phase=phase,
    )


async def test_completion_scores_the_session_from_its_own_phased_attempts(
    clean_engine: AsyncEngine,
) -> None:
    """No scores travel in the request: the client has none to send."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
            await seed_question(session, "q-pre", session_id=session_id)
            await seed_question(session, "q-post", session_id=session_id)
            await seed_attempt(
                session,
                session_id,
                "q-pre",
                self_rating=AGAIN,
                phase=AttemptPhase.PRE_TEST,
                request_id="a-1",
            )
            await seed_attempt(
                session,
                session_id,
                "q-post",
                self_rating=EASY,
                phase=AttemptPhase.POST_TEST,
                request_id="a-2",
            )
            await seed_reflection(session, session_id)
        await harness.login()

        response = await harness.client.post(
            f"/api/study/sessions/{session_id}/complete",
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["pre_test_score"] == pytest.approx(0.0)
    assert body["session"]["post_test_score"] == pytest.approx(1.0)
    assert body["session"]["improvement"] == pytest.approx(1.0)


async def test_practice_attempts_do_not_count_towards_either_end(
    clean_engine: AsyncEngine,
) -> None:
    """Answering well while still studying is not a post-test result."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
            await seed_question(session, "q-pre", session_id=session_id)
            await seed_question(session, "q-practice", session_id=session_id)
            await seed_attempt(
                session,
                session_id,
                "q-pre",
                self_rating=HARD,
                phase=AttemptPhase.PRE_TEST,
                request_id="a-1",
            )
            await seed_attempt(
                session,
                session_id,
                "q-practice",
                self_rating=EASY,
                phase=AttemptPhase.PRACTICE,
                request_id="a-2",
            )
            await seed_reflection(session, session_id)
        await harness.login()

        response = await harness.client.post(
            f"/api/study/sessions/{session_id}/complete",
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["pre_test_score"] == pytest.approx(0.3)
    assert body["session"]["post_test_score"] is None
    assert body["session"]["improvement"] is None


async def test_summary_holds_the_prediction_against_measured_performance(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
            await record_study_prediction(
                session,
                TOPIC,
                LEARNING_PATH_ID,
                5,
                session_id=session_id,
                user_id="learner",
                request_id="pred-1",
            )
            await seed_question(session, "q-post", session_id=session_id)
            await seed_attempt(
                session,
                session_id,
                "q-post",
                self_rating=AGAIN,
                phase=AttemptPhase.POST_TEST,
                request_id="a-1",
            )
            await seed_reflection(session, session_id)
        await harness.login()

        await harness.client.post(
            f"/api/study/sessions/{session_id}/complete",
            headers=harness.csrf_headers(),
        )
        response = await harness.client.get(f"/api/study/sessions/{session_id}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["predicted"] == pytest.approx(1.0)
    assert body["measured"] == pytest.approx(0.0)
    assert body["calibration_delta"] == pytest.approx(-1.0)
    assert body["band"] == "overconfident"
    assert body["attempts"] == {"pre_test": 0, "practice": 0, "post_test": 1}


async def test_summary_falls_back_to_practice_before_the_post_test(
    clean_engine: AsyncEngine,
) -> None:
    """A learner who reflects mid-session still gets a comparison, not a blank."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
            await record_study_prediction(
                session,
                TOPIC,
                LEARNING_PATH_ID,
                4,
                session_id=session_id,
                user_id="learner",
                request_id="pred-1",
            )
            await seed_question(session, "q-practice", session_id=session_id)
            await seed_attempt(
                session,
                session_id,
                "q-practice",
                self_rating=GOOD,
                phase=AttemptPhase.PRACTICE,
                request_id="a-1",
            )
        await harness.login()

        response = await harness.client.get(f"/api/study/sessions/{session_id}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["practice_score"] == pytest.approx(0.7)
    assert body["measured"] == pytest.approx(0.7)
    assert body["band"] == "well_calibrated"


async def test_summary_rejects_a_session_owned_by_another_learner(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, user_id="somebody-else")
        await harness.login("learner")

        response = await harness.client.get(f"/api/study/sessions/{session_id}/summary")

    assert response.status_code == 404


async def test_completion_rejects_a_session_owned_by_another_learner(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, user_id="somebody-else")
        await harness.login("learner")

        response = await harness.client.post(
            f"/api/study/sessions/{session_id}/complete",
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 404


async def test_session_questions_read_back_in_generation_order(
    clean_engine: AsyncEngine,
) -> None:
    """A reload must return the same cards, in the same order, for free."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
            other_session_id = await seed_session(session)
            for index in range(3):
                await seed_question(session, f"q-{index}", session_id=session_id)
            await seed_question(session, "q-other", session_id=other_session_id)
            await seed_question(session, "q-loose")
        await harness.login()

        response = await harness.client.get(f"/api/study/sessions/{session_id}/questions")

    assert response.status_code == 200
    body = response.json()
    assert [question["id"] for question in body["questions"]] == ["q-0", "q-1", "q-2"]
    assert body["questions"][0]["engagement_policy"]["kind"] == "elaboration"


async def test_session_questions_reject_a_session_owned_by_another_learner(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, user_id="somebody-else")
        await harness.login("learner")

        response = await harness.client.get(f"/api/study/sessions/{session_id}/questions")

    assert response.status_code == 404


async def test_completion_refuses_a_session_with_no_reflection(
    clean_engine: AsyncEngine,
) -> None:
    """The abuse case: a client that never renders the countdown still POSTs here."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
        await harness.login()

        response = await harness.client.post(
            f"/api/study/sessions/{session_id}/complete",
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 412
    assert response.json()["detail"]["code"] == "engagement.policy_unmet"


async def test_completion_refuses_a_reflection_inside_the_floor(
    clean_engine: AsyncEngine,
) -> None:
    """Reflecting two seconds in is not reflecting, whatever the client displayed."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
            await seed_reflection(session, session_id, seconds_after_start=2)
        await harness.login()

        response = await harness.client.post(
            f"/api/study/sessions/{session_id}/complete",
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 412
    assert response.json()["detail"]["params"]["required"] == "reflection_pacing"


async def test_session_questions_report_what_the_learner_already_answered(
    clean_engine: AsyncEngine,
) -> None:
    """A resumed session picks up after these rather than restarting at card one."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
            for index in range(3):
                await seed_question(session, f"q-{index}", session_id=session_id)
            await seed_attempt(
                session,
                session_id,
                "q-0",
                self_rating=GOOD,
                phase=AttemptPhase.PRE_TEST,
                request_id="a-1",
            )
            await seed_attempt(
                session,
                session_id,
                "q-1",
                self_rating=GOOD,
                phase=AttemptPhase.PRACTICE,
                request_id="a-2",
            )
            # Another learner's attempt on the same session must not count as ours.
            await seed_attempt(
                session,
                session_id,
                "q-2",
                self_rating=GOOD,
                phase=AttemptPhase.PRACTICE,
                request_id="a-3",
                user_id="somebody-else",
            )
        await harness.login()

        response = await harness.client.get(f"/api/study/sessions/{session_id}/questions")

    assert response.status_code == 200
    assert response.json()["attempted_question_ids"] == ["q-0", "q-1"]
