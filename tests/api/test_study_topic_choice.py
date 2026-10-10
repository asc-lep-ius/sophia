"""Starting a study session on a topic picked from the learning path's list (#130).

Runs the real routes against Postgres rather than the e2e fixture: the browser
offers the strings ``/topics`` returns, so the proof is that the session the
API starts carries exactly that string after #127 filed topics by course.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import insert

from sophia.infra.schema import lecture_modules, transcript_segments, transcriptions
from sophia.services.athena_confidence import rate_confidence, update_actual_score

from ._db_harness import db_harness

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


pytestmark = pytest.mark.postgres

LEARNING_PATH_ID = 12
# EP1 2026W's second module: its id is not the learning path's, as no real
# course's is (#127).
LECTURE_MODULE_ID = 3022498
TOPICS = ["Schleifen", "Arrays und Referenzen", "Rekursion"]


async def _seed_lecture(session: AsyncSession) -> None:
    await session.execute(
        insert(lecture_modules).values(
            module_id=LECTURE_MODULE_ID, course_id=str(LEARNING_PATH_ID), course_name="EP1"
        )
    )
    await session.execute(
        insert(transcriptions).values(
            episode_id="ep-w2", module_id=LECTURE_MODULE_ID, status="completed"
        )
    )
    await session.execute(
        insert(transcript_segments).values(
            episode_id="ep-w2", segment_index=0, start_time=0.0, end_time=1.0, text="Arrays"
        )
    )


async def _seed_gap(session: AsyncSession, topic: str, *, rating: int, actual: float) -> None:
    await rate_confidence(session, topic, LEARNING_PATH_ID, rating)
    await update_actual_score(session, topic, LEARNING_PATH_ID, actual)


async def test_a_session_starts_on_exactly_the_topic_picked_from_the_list(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    extractor = MagicMock()
    extractor.extract_topics = AsyncMock(return_value=TOPICS)
    monkeypatch.setattr(
        "sophia.services.athena_topics.create_topic_extractor", lambda _app: extractor
    )

    async with db_harness(clean_engine) as harness:
        async with harness.seed() as session:
            await _seed_lecture(session)
            # Predicted 100%, scored 20%: the largest overshoot, so the topic
            # the study page offers first.
            await _seed_gap(session, "Arrays und Referenzen", rating=5, actual=0.2)
            await _seed_gap(session, "Rekursion", rating=3, actual=0.4)
        await harness.login()
        extracted = await harness.client.post(
            f"/api/learning-paths/{LEARNING_PATH_ID}/topics/extract",
            json={"content_source_id": LECTURE_MODULE_ID},
            headers=harness.csrf_headers(),
        )
        listed = await harness.client.get(f"/api/learning-paths/{LEARNING_PATH_ID}/topics")
        rated = await harness.client.get(
            f"/api/learning-paths/{LEARNING_PATH_ID}/topics/confidence"
        )

        offered = {topic["topic"] for topic in listed.json()["topics"]}
        gaps = {r["topic"]: r["calibration_error"] for r in rated.json()["ratings"]}
        chosen = max(offered, key=lambda topic: gaps.get(topic) or 0.0)

        started = await harness.client.post(
            "/api/study/sessions",
            json={"learning_path_id": LEARNING_PATH_ID, "topic": chosen},
            headers=harness.csrf_headers(),
        )
        sessions = await harness.client.get(
            "/api/study/sessions", params={"learning_path_id": LEARNING_PATH_ID}
        )

    assert extracted.status_code == 200
    assert offered == set(TOPICS)
    assert chosen == "Arrays und Referenzen"
    assert started.status_code == 200
    session_body = started.json()["session"]
    assert session_body["topic"] == chosen
    assert session_body["learning_path_id"] == LEARNING_PATH_ID
    assert [(s["id"], s["topic"]) for s in sessions.json()["sessions"]] == [
        (session_body["id"], chosen)
    ]
