"""Idempotent study-realtime submission endpoints: predictions, self-explanations,
reflections, and session-scoped flashcards."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from sophia.api.schemas.study import StudyFlashcardRequest
from sophia.domain.models import FlashcardSource
from sophia.infra.schema import (
    confidence_ratings,
    self_explanations,
    student_flashcards,
    study_events,
    study_reflections,
)
from sophia.services.athena_session import save_flashcard, start_study_session

from ._db_harness import db_harness, learning_path_tenant

if TYPE_CHECKING:
    from typing import Any

    from sqlalchemy import Table
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

    from ._db_harness import DbHarness

pytestmark = pytest.mark.postgres

LEARNING_PATH_ID = 12


async def seed_session(session: AsyncSession, *, user_id: str = "learner") -> int:
    study_session = await start_study_session(session, LEARNING_PATH_ID, "Graphs", user_id=user_id)
    return study_session.id


async def row_count(harness: DbHarness, table: Table) -> int:
    async with harness.seed() as session:
        return await session.scalar(select(func.count()).select_from(table)) or 0


async def event_types(harness: DbHarness, session_id: int) -> list[str]:
    async with harness.seed() as session:
        rows = (
            await session.execute(
                select(study_events.c.event_type)
                .where(study_events.c.session_id == session_id)
                .order_by(study_events.c.id)
            )
        ).all()
        return [row.event_type for row in rows]


async def test_prediction_is_idempotent_and_logs_an_event(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
        await harness.login()

        body = {
            "learning_path_id": LEARNING_PATH_ID,
            "session_id": session_id,
            "topic": "Graphs",
            "rating": 4,
            "request_id": "pred-1",
        }
        first = await harness.client.post(
            "/api/study/predictions", json=body, headers=harness.csrf_headers()
        )
        retry = await harness.client.post(
            "/api/study/predictions", json=body, headers=harness.csrf_headers()
        )
        stored = await row_count(harness, confidence_ratings)
        events = await event_types(harness, session_id)

    assert first.status_code == 200
    assert retry.status_code == 200
    assert first.json() == retry.json()
    assert stored == 1
    assert events == ["prediction_recorded"]


async def test_prediction_rejects_a_session_owned_by_another_learner(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session, user_id="somebody-else")
        await harness.login("learner")

        response = await harness.client.post(
            "/api/study/predictions",
            json={
                "learning_path_id": LEARNING_PATH_ID,
                "session_id": session_id,
                "topic": "Graphs",
                "rating": 4,
                "request_id": "pred-1",
            },
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 404


async def test_prediction_rejects_a_legacy_session_with_no_owner(
    clean_engine: AsyncEngine,
) -> None:
    """A session started before study realtime tracked ownership has user_id
    NULL and can never satisfy an ownership check — see get_session_scope."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            legacy_session = await start_study_session(session, LEARNING_PATH_ID, "Graphs")
        await harness.login()

        response = await harness.client.post(
            "/api/study/predictions",
            json={
                "learning_path_id": LEARNING_PATH_ID,
                "session_id": legacy_session.id,
                "topic": "Graphs",
                "rating": 4,
                "request_id": "pred-1",
            },
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 404


async def test_concurrent_duplicate_predictions_create_exactly_one_row(
    clean_engine: AsyncEngine,
) -> None:
    """Two racing retries of the same request_id must not double-write."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
        await harness.login()

        body = {
            "learning_path_id": LEARNING_PATH_ID,
            "session_id": session_id,
            "topic": "Graphs",
            "rating": 3,
            "request_id": "pred-race",
        }
        responses = await asyncio.gather(
            *(
                harness.client.post(
                    "/api/study/predictions", json=body, headers=harness.csrf_headers()
                )
                for _ in range(5)
            )
        )
        stored = await row_count(harness, confidence_ratings)

    assert all(response.status_code == 200 for response in responses)
    assert stored == 1


async def test_self_explanation_is_idempotent(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
            flashcard = await save_flashcard(session, LEARNING_PATH_ID, "Graphs", "Q?", "A.")
        await harness.login()

        body = {
            "learning_path_id": LEARNING_PATH_ID,
            "session_id": session_id,
            "flashcard_id": flashcard.id,
            "student_explanation": "Because the cut separates source from sink.",
            "scaffold_level": 2,
            "request_id": "expl-1",
        }
        first = await harness.client.post(
            "/api/study/self-explanations", json=body, headers=harness.csrf_headers()
        )
        retry = await harness.client.post(
            "/api/study/self-explanations", json=body, headers=harness.csrf_headers()
        )
        stored = await row_count(harness, self_explanations)
        events = await event_types(harness, session_id)

    assert first.status_code == 200
    assert retry.status_code == 200
    assert first.json() == retry.json()
    assert stored == 1
    assert events == ["self_explanation_recorded"]


async def test_self_explanation_rejects_a_flashcard_from_another_course(
    clean_engine: AsyncEngine,
) -> None:
    other_course_id = 99
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
            flashcard = await save_flashcard(session, other_course_id, "Other", "Q?", "A.")
        await harness.login()

        response = await harness.client.post(
            "/api/study/self-explanations",
            json={
                "learning_path_id": LEARNING_PATH_ID,
                "session_id": session_id,
                "flashcard_id": flashcard.id,
                "student_explanation": "Because...",
                "request_id": "expl-1",
            },
            headers=harness.csrf_headers(),
        )

    assert response.status_code == 404


async def test_reflection_is_idempotent_and_persists_text(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
        await harness.login()

        body = {
            "learning_path_id": LEARNING_PATH_ID,
            "session_id": session_id,
            "prompt": "Which question was hardest?",
            "reflection_text": "The minimum cut proof took me a while.",
            "request_id": "refl-1",
        }
        first = await harness.client.post(
            "/api/study/reflections", json=body, headers=harness.csrf_headers()
        )
        retry = await harness.client.post(
            "/api/study/reflections", json=body, headers=harness.csrf_headers()
        )
        stored = await row_count(harness, study_reflections)
        events = await event_types(harness, session_id)

    assert first.status_code == 200
    assert retry.status_code == 200
    assert first.json() == retry.json()
    assert first.json()["reflection"]["reflection_text"] == body["reflection_text"]
    assert stored == 1
    assert events == ["reflection_recorded"]


async def test_flashcard_without_session_saves_unconditionally_as_before(
    clean_engine: AsyncEngine,
) -> None:
    """No session_id/request_id: the pre-realtime, non-idempotent path."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        await harness.login()

        body = {
            "learning_path_id": LEARNING_PATH_ID,
            "topic": "Graphs",
            "front": "Q?",
            "back": "A.",
        }
        first = await harness.client.post(
            "/api/study/flashcards", json=body, headers=harness.csrf_headers()
        )
        second = await harness.client.post(
            "/api/study/flashcards", json=body, headers=harness.csrf_headers()
        )
        stored = await row_count(harness, student_flashcards)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["flashcard"]["id"] != second.json()["flashcard"]["id"]
    assert stored == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"session_id": 1},
        {"request_id": "req-1"},
    ],
)
def test_flashcard_request_rejects_half_of_the_idempotency_pair(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError, match="session_id and request_id"):
        StudyFlashcardRequest(
            learning_path_id=LEARNING_PATH_ID,
            topic="Graphs",
            front="Q?",
            back="A.",
            **overrides,
        )


async def test_flashcard_rejects_session_id_given_without_request_id(
    clean_engine: AsyncEngine,
) -> None:
    """Half the idempotency pair must not silently fall back to the
    non-idempotent path — that's the request the client actually made."""
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
        await harness.login()

        response = await harness.client.post(
            "/api/study/flashcards",
            json={
                "learning_path_id": LEARNING_PATH_ID,
                "topic": "Graphs",
                "front": "Q?",
                "back": "A.",
                "session_id": session_id,
            },
            headers=harness.csrf_headers(),
        )

    # The error envelope redacts field-level validation detail by design
    # (see request.validation_failed elsewhere in this suite) — status code
    # is the only thing to assert at this layer.
    assert response.status_code == 422


async def test_flashcard_with_session_is_idempotent(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            session_id = await seed_session(session)
        await harness.login()

        body = {
            "learning_path_id": LEARNING_PATH_ID,
            "topic": "Graphs",
            "front": "Q?",
            "back": "A.",
            "source": FlashcardSource.STUDY.value,
            "session_id": session_id,
            "request_id": "card-1",
        }
        first = await harness.client.post(
            "/api/study/flashcards", json=body, headers=harness.csrf_headers()
        )
        retry = await harness.client.post(
            "/api/study/flashcards", json=body, headers=harness.csrf_headers()
        )
        stored = await row_count(harness, student_flashcards)
        events = await event_types(harness, session_id)

    assert first.status_code == 200
    assert retry.status_code == 200
    assert first.json()["flashcard"]["id"] == retry.json()["flashcard"]["id"]
    assert stored == 1
    assert events == ["flashcard_saved"]
