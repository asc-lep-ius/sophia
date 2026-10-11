"""Reconciling the prediction with the result once the numbers open (#167).

Driven through the real routers against Postgres: what is under test is the
server's own judgement of the band, the refusal to close a miscalibrated
session without an explanation, and what a later session reads back — none of
which the e2e fixture computes for itself.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import func, select, update

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
from sophia.infra.schema import confidence_ratings, study_sessions
from sophia.services.athena_session import save_reflection, start_study_session
from sophia.services.provenance import record_provenance
from sophia.services.study_questions import _insert_question, save_attempt

from ._db_harness import db_harness, learning_path_tenant

if TYPE_CHECKING:
    from httpx import Response
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from ._db_harness import DbHarness

pytestmark = pytest.mark.postgres

LEARNING_PATH_ID = 12
TOPIC = "Graphs"
# save_attempt maps Again/Hard/Good/Easy onto 0.0/0.3/0.7/1.0.
AGAIN, EASY = 1, 4
NOT_AT_ALL, VERY_WELL = 1, 5
GAP = "I could recite the definition but never traced a cut by hand."


async def seed_session(
    session: AsyncSession,
    *,
    post_test: int | None,
    topic: str = TOPIC,
    user_id: str = "learner",
) -> int:
    """A session with a paced reflection and, if given, a graded post-test."""
    study_session = await start_study_session(session, LEARNING_PATH_ID, topic, user_id=user_id)
    session_id = study_session.id
    question_id = f"q-{session_id}"
    await _seed_question(session, question_id, session_id, topic)
    if post_test is not None:
        await save_attempt(
            session,
            LEARNING_PATH_ID,
            question_id,
            user_id,
            "An answer long enough to count as elaboration.",
            4,
            session_id=session_id,
            request_id=f"a-{session_id}",
            self_rating=post_test,
            phase=AttemptPhase.POST_TEST,
        )
    await save_reflection(
        session,
        session_id,
        LEARNING_PATH_ID,
        user_id,
        "Which part still feels unfinished?",
        "The cut argument took me a while.",
        request_id=f"refl-{session_id}",
    )
    # Completion refuses a reflection inside the pacing floor.
    await session.execute(
        update(study_sessions)
        .where(study_sessions.c.id == session_id)
        .values(started_at=datetime.now(UTC) - timedelta(seconds=60))
    )
    return session_id


async def _seed_question(
    session: AsyncSession,
    question_id: str,
    session_id: int,
    topic: str,
) -> None:
    """Insert a question directly: generation itself needs a model provider."""
    await _insert_question(
        session,
        GeneratedQuestion(
            id=question_id,
            course_id=LEARNING_PATH_ID,
            topic=topic,
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
        ),
    )
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


async def predict(
    harness: DbHarness,
    session_id: int,
    rating: int,
    *,
    reason: str | None = None,
    topic: str = TOPIC,
) -> Response:
    return await harness.client.post(
        "/api/study/predictions",
        json={
            "learning_path_id": LEARNING_PATH_ID,
            "session_id": session_id,
            "topic": topic,
            "rating": rating,
            "request_id": f"pred-{session_id}-{rating}",
            "reason": reason,
        },
        headers=harness.csrf_headers(),
    )


async def reconcile(harness: DbHarness, session_id: int, text: str = GAP) -> Response:
    return await harness.client.post(
        "/api/study/reconciliations",
        json={
            "learning_path_id": LEARNING_PATH_ID,
            "session_id": session_id,
            "reconciliation_text": text,
            "request_id": f"rec-{session_id}",
        },
        headers=harness.csrf_headers(),
    )


async def complete(harness: DbHarness, session_id: int) -> Response:
    return await harness.client.post(
        f"/api/study/sessions/{session_id}/complete",
        headers=harness.csrf_headers(),
    )


async def summary(harness: DbHarness, session_id: int) -> dict[str, Any]:
    response = await harness.client.get(f"/api/study/sessions/{session_id}/summary")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(
    ("rating", "post_test", "band"),
    [(VERY_WELL, AGAIN, "overconfident"), (NOT_AT_ALL, EASY, "underconfident")],
)
async def test_completion_refuses_a_miscalibrated_session_without_a_reconciliation(
    clean_engine: AsyncEngine,
    rating: int,
    post_test: int,
    band: str,
) -> None:
    """The abuse case: a client that never renders the prompt still POSTs here."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, post_test=post_test)
        await harness.login()
        await predict(harness, session_id, rating)

        response = await complete(harness, session_id)
        after = await summary(harness, session_id)

    assert response.status_code == 412
    assert response.json()["detail"]["code"] == "engagement.policy_unmet"
    assert response.json()["detail"]["params"] == {"required": "reconciliation", "band": band}
    assert after["reconciliation_required"] is True
    assert after["session"]["completed_at"] is None


async def test_a_reconciliation_lets_a_miscalibrated_session_complete(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, post_test=AGAIN)
        await harness.login()
        await predict(harness, session_id, VERY_WELL)

        saved = await reconcile(harness, session_id)
        completed = await complete(harness, session_id)
        after = await summary(harness, session_id)

    assert saved.status_code == 200, saved.text
    assert completed.status_code == 200, completed.text
    assert after["reconciliation"]["reconciliation_text"] == GAP


async def test_a_reconciliation_stores_the_prediction_score_and_band_it_answered(
    clean_engine: AsyncEngine,
) -> None:
    """Server-computed, so it reads against what the learner actually saw."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, post_test=AGAIN)
        await harness.login()
        await predict(harness, session_id, VERY_WELL)

        response = await reconcile(harness, session_id)

    assert response.status_code == 200, response.text
    stored = response.json()["reconciliation"]
    assert stored["predicted"] == pytest.approx(1.0)
    assert stored["measured"] == pytest.approx(0.0)
    assert stored["band"] == "overconfident"


async def test_a_well_calibrated_session_completes_without_a_reconciliation(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, post_test=EASY)
        await harness.login()
        await predict(harness, session_id, VERY_WELL)
        before = await summary(harness, session_id)

        response = await complete(harness, session_id)

    assert before["band"] == "well_calibrated"
    assert before["reconciliation_required"] is False
    assert response.status_code == 200, response.text


async def test_a_well_calibrated_session_may_still_be_reconciled(
    clean_engine: AsyncEngine,
) -> None:
    """Offered but optional: the learner who wants to note why is not refused."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, post_test=EASY)
        await harness.login()
        await predict(harness, session_id, VERY_WELL)

        response = await reconcile(harness, session_id)

    assert response.status_code == 200, response.text
    assert response.json()["reconciliation"]["band"] == "well_calibrated"


async def test_a_reconciliation_needs_a_prediction_to_compare(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, post_test=AGAIN)
        await harness.login()

        response = await reconcile(harness, session_id)

    assert response.status_code == 412
    assert response.json()["detail"]["params"]["required"] == "calibration"


async def test_a_blank_reconciliation_is_refused(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, post_test=AGAIN)
        await harness.login()
        await predict(harness, session_id, VERY_WELL)

        response = await reconcile(harness, session_id, "   ")

    assert response.status_code == 422


async def test_reconciliation_rejects_a_session_owned_by_another_learner(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, post_test=AGAIN, user_id="somebody-else")
        await harness.login("learner")

        response = await reconcile(harness, session_id)

    assert response.status_code == 404


async def test_the_results_open_before_the_session_closes(clean_engine: AsyncEngine) -> None:
    """Completion waits on the reconciliation, so the summary cannot wait on completion."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, post_test=EASY)
        await harness.login()

        body = await summary(harness, session_id)

    assert body["session"]["completed_at"] is None
    assert body["session"]["post_test_score"] == pytest.approx(1.0)
    assert body["measured"] == pytest.approx(1.0)
    assert body["reflected"] is True


async def test_the_reason_is_stored_with_the_rating_and_shown_with_the_results(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, post_test=AGAIN)
        await harness.login()

        response = await predict(harness, session_id, VERY_WELL, reason="  I did the lab.  ")
        body = await summary(harness, session_id)

    assert response.status_code == 200, response.text
    assert response.json()["prediction"]["reason"] == "I did the lab."
    assert body["prediction_reason"] == "I did the lab."


async def test_a_reason_typed_after_the_rating_lands_on_the_same_prediction(
    clean_engine: AsyncEngine,
) -> None:
    """Re-recording the prediction would void the outcome its pre-test grade wrote."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, post_test=AGAIN)
        await harness.login()
        await predict(harness, session_id, VERY_WELL)

        response = await harness.client.put(
            f"/api/study/sessions/{session_id}/prediction/reason",
            json={"reason": "I did the lab."},
            headers=harness.csrf_headers(),
        )
        body = await summary(harness, session_id)
        async with harness.seed() as session:
            ratings = await session.scalar(
                select(func.count()).where(confidence_ratings.c.session_id == session_id)
            )

    assert response.status_code == 200, response.text
    assert body["prediction_reason"] == "I did the lab."
    assert body["predicted"] == pytest.approx(1.0)
    assert ratings == 1


async def test_a_reason_before_any_prediction_is_refused(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, post_test=None)
        await harness.login()

        response = await harness.client.put(
            f"/api/study/sessions/{session_id}/prediction/reason",
            json={"reason": "I did the lab."},
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 404


async def test_a_later_session_on_the_topic_reads_the_last_reconciliation_back(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            earlier = await seed_session(session, post_test=AGAIN)
        await harness.login()
        await predict(harness, earlier, VERY_WELL)
        await reconcile(harness, earlier)
        await complete(harness, earlier)
        async with harness.seed() as session:
            later = await seed_session(session, post_test=None)

        body = await summary(harness, later)
        own = await summary(harness, earlier)

    previous = body["previous_reconciliation"]
    assert previous["reconciliation_text"] == GAP
    assert previous["predicted"] == pytest.approx(1.0)
    assert previous["measured"] == pytest.approx(0.0)
    assert previous["band"] == "overconfident"
    assert own["previous_reconciliation"] is None


@pytest.mark.parametrize(
    ("topic", "user_id"),
    [("Sorting", "learner"), (TOPIC, "somebody-else")],
    ids=["another-topic", "another-learner"],
)
async def test_a_reconciliation_is_read_back_only_on_its_own_topic_and_learner(
    clean_engine: AsyncEngine,
    topic: str,
    user_id: str,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            earlier = await seed_session(session, post_test=AGAIN)
            later = await seed_session(session, post_test=None, topic=topic, user_id=user_id)
        await harness.login()
        await predict(harness, earlier, VERY_WELL)
        await reconcile(harness, earlier)
        await harness.login(user_id)

        body = await summary(harness, later)

    assert body["previous_reconciliation"] is None
