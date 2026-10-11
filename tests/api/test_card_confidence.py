"""Per-card calibration on /app/calibration: sure answers that met Again (#169)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sophia.domain.learning import ContentLanguage, GeneratedQuestion, QuestionKind
from sophia.infra.schema import question_attempts
from sophia.services.study_questions import _insert_question

from ._db_harness import db_harness, learning_path_tenant

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.postgres

LEARNING_PATH_ID = 12
OTHER_LEARNING_PATH_ID = 13
AGAIN, HARD, GOOD = 1, 2, 3


async def seed_question(
    session: AsyncSession, question_id: str, topic: str, *, course_id: int = LEARNING_PATH_ID
) -> None:
    await _insert_question(
        session,
        GeneratedQuestion(
            id=question_id,
            course_id=course_id,
            topic=topic,
            kind=QuestionKind.OPEN_RESPONSE,
            prompt=f"Explain {topic}.",
            difficulty="explain",
            content_language=ContentLanguage.DE,
        ),
    )


async def seed_attempt(
    session: AsyncSession,
    question_id: str,
    *,
    confidence: int | None,
    self_rating: int,
    user_id: str = "learner",
    course_id: int = LEARNING_PATH_ID,
) -> None:
    await session.execute(
        question_attempts.insert().values(
            course_id=course_id,
            question_id=question_id,
            user_id=user_id,
            answer_text="An answer.",
            confidence=confidence,
            self_rating=self_rating,
        )
    )


async def test_counts_sure_answers_and_the_agains_among_them_per_topic(
    clean_engine: AsyncEngine,
) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        async with harness.seed() as session:
            await seed_question(session, "graphs-1", "Graphs")
            await seed_question(session, "graphs-2", "Graphs")
            await seed_question(session, "trees-1", "Trees")
            await seed_question(session, "heaps-1", "Heaps")
            await seed_question(session, "elsewhere-1", "Graphs", course_id=OTHER_LEARNING_PATH_ID)

            # Sure and Again, twice; sure and Hard; unsure and Again.
            await seed_attempt(session, "graphs-1", confidence=5, self_rating=AGAIN)
            await seed_attempt(session, "graphs-1", confidence=4, self_rating=HARD)
            await seed_attempt(session, "graphs-2", confidence=4, self_rating=AGAIN)
            await seed_attempt(session, "graphs-2", confidence=2, self_rating=AGAIN)
            # From before cards asked: no confidence, so not read as unsure.
            await seed_attempt(session, "graphs-2", confidence=None, self_rating=AGAIN)
            await seed_attempt(session, "trees-1", confidence=3, self_rating=GOOD)
            await seed_attempt(session, "heaps-1", confidence=None, self_rating=AGAIN)
            # Somebody else's, and another course's.
            await seed_attempt(
                session, "graphs-1", confidence=5, self_rating=AGAIN, user_id="somebody-else"
            )
            await seed_attempt(
                session,
                "elsewhere-1",
                confidence=5,
                self_rating=AGAIN,
                course_id=OTHER_LEARNING_PATH_ID,
            )
        await harness.login()

        response = await harness.client.get(
            "/api/calibration/card-confidence", params={"learning_path_id": LEARNING_PATH_ID}
        )

    assert response.status_code == 200, response.json()
    assert response.json() == {
        "learning_path_id": LEARNING_PATH_ID,
        "topics": [
            {"topic": "Graphs", "rated": 4, "sure": 3, "sure_again": 2},
            {"topic": "Trees", "rated": 1, "sure": 0, "sure_again": 0},
        ],
        "unrated": 2,
    }


async def test_another_learning_path_is_refused(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        await harness.login()

        response = await harness.client.get(
            "/api/calibration/card-confidence",
            params={"learning_path_id": OTHER_LEARNING_PATH_ID},
        )

    assert response.status_code == 403


async def test_requires_a_signed_in_learner(clean_engine: AsyncEngine) -> None:
    async with db_harness(clean_engine, tenant=learning_path_tenant(LEARNING_PATH_ID)) as harness:
        response = await harness.client.get(
            "/api/calibration/card-confidence", params={"learning_path_id": LEARNING_PATH_ID}
        )

    assert response.status_code == 401
