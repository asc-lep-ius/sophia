"""A finished study session comes back on review, across every course (#131).

Runs the real routes against Postgres rather than the e2e fixture: what is under
test is that finishing a session through the browser's completion path writes
the schedule ``/app/review`` reads, and that a review in one course can be read
and graded while another course is selected.

Only the clock is faked, by moving a written ``next_review_at`` into the past:
the first review falls due a day after the session, and a test cannot wait.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import insert, select, update

from sophia.api.routers import deadlines as deadlines_router
from sophia.domain.models import Course, Deadline
from sophia.infra.schema import deadline_cache, review_schedule
from sophia.services.athena_review import (
    FSRS_DEFAULT_DIFFICULTY,
    FSRS_DEFAULT_STABILITY,
    SELF_RATING_SCORES,
    compute_fsrs_interval,
)

from ._db_harness import DbHarness, db_harness, learning_path_tenant
from ._session_helpers import FakeMoodle

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


pytestmark = pytest.mark.postgres

EP1 = Course(id=82774, fullname="185.A79 Einführung in die Programmierung 1", shortname="EP1")
GDS = Course(id=83629, fullname="192.134 Grundlagen digitaler Systeme", shortname="GDS")
TOPIC = "Rekursive Methoden"
GOOD = 3
# Loose enough for the seconds between the request and the assertion.
CLOCK_SLACK = timedelta(seconds=30)


def _harness(engine: AsyncEngine):
    return db_harness(
        engine,
        tenant=learning_path_tenant(EP1.id),
        moodle=FakeMoodle(courses=[EP1, GDS]),
        # The reflection floor has its own tests; here it would only be a wait.
        settings_overrides={"study_reflection_min_seconds": 0},
    )


async def _finish_session(harness: DbHarness, topic: str = TOPIC) -> int:
    """Start, reflect on and complete a session the way the reflect page does."""
    started = await harness.client.post(
        "/api/study/sessions",
        json={"learning_path_id": EP1.id, "topic": topic},
        headers=harness.csrf_headers(),
    )
    assert started.status_code == 200, started.text
    session_id = started.json()["session"]["id"]
    reflected = await harness.client.post(
        "/api/study/reflections",
        json={
            "learning_path_id": EP1.id,
            "session_id": session_id,
            "prompt": "Which part still feels unfinished?",
            "reflection_text": "The base case took me a while.",
            "request_id": f"reflection-{session_id}",
        },
        headers=harness.csrf_headers(),
    )
    assert reflected.status_code == 200, reflected.text
    await _complete(harness, session_id)
    return session_id


async def _complete(harness: DbHarness, session_id: int) -> None:
    completed = await harness.client.post(
        f"/api/study/sessions/{session_id}/complete",
        headers=harness.csrf_headers(),
    )
    assert completed.status_code == 200, completed.text


async def _select(harness: DbHarness, course: Course) -> None:
    response = await harness.client.put(
        "/api/learning-paths/selection",
        json={"learning_path_id": course.id},
        headers=harness.csrf_headers(),
    )
    assert response.status_code == 200, response.text


async def _next_review_at(harness: DbHarness, topic: str = TOPIC) -> datetime | None:
    async with harness.seed() as session:
        return await session.scalar(
            select(review_schedule.c.next_review_at).where(
                review_schedule.c.topic == topic,
                review_schedule.c.course_id == EP1.id,
            )
        )


async def _fall_due(harness: DbHarness, topic: str = TOPIC) -> None:
    async with harness.seed() as session:
        await session.execute(
            update(review_schedule)
            .where(review_schedule.c.topic == topic, review_schedule.c.course_id == EP1.id)
            .values(next_review_at=datetime.now(UTC) - timedelta(minutes=1))
        )


def _assert_close(actual: datetime | str, expected: datetime) -> None:
    moment = datetime.fromisoformat(actual) if isinstance(actual, str) else actual
    assert abs(moment - expected) < CLOCK_SLACK, (moment, expected)


async def test_a_finished_session_comes_back_due_while_another_course_is_selected(
    clean_engine: AsyncEngine,
) -> None:
    async with _harness(clean_engine) as harness:
        await harness.login()
        await _finish_session(harness)

        # The schedule rule's first interval: one day after finishing.
        written = await _next_review_at(harness)
        assert written is not None
        _assert_close(written, datetime.now(UTC) + timedelta(days=1))

        # Not due yet, but /app/review can say when it will be.
        await _select(harness, GDS)
        not_yet = await harness.client.get("/api/review/due")
        upcoming = await harness.client.get("/api/review/upcoming?days_ahead=365")
        assert not_yet.json()["reviews"] == []
        assert [(r["topic"], r["learning_path_id"]) for r in upcoming.json()["reviews"]] == [
            (TOPIC, EP1.id)
        ]

        await _fall_due(harness)
        due = await harness.client.get("/api/review/due")
        assert due.status_code == 200
        assert [(r["topic"], r["learning_path_id"]) for r in due.json()["reviews"]] == [
            (TOPIC, EP1.id)
        ]

        graded = await harness.client.post(
            "/api/review/complete",
            json={"learning_path_id": EP1.id, "topic": TOPIC, "self_rating": GOOD},
            headers=harness.csrf_headers(),
        )

    assert graded.status_code == 200, graded.text
    _, _, interval_days = compute_fsrs_interval(
        FSRS_DEFAULT_DIFFICULTY, FSRS_DEFAULT_STABILITY, SELF_RATING_SCORES[GOOD]
    )
    schedule = graded.json()["schedule"]
    assert schedule["review_count"] == 1
    _assert_close(schedule["next_review_at"], datetime.now(UTC) + timedelta(days=interval_days))


async def test_a_session_that_is_never_completed_schedules_nothing(
    clean_engine: AsyncEngine,
) -> None:
    async with _harness(clean_engine) as harness:
        await harness.login()
        started = await harness.client.post(
            "/api/study/sessions",
            json={"learning_path_id": EP1.id, "topic": TOPIC},
            headers=harness.csrf_headers(),
        )
        assert started.status_code == 200

        assert await _next_review_at(harness) is None


async def test_completing_the_same_session_again_keeps_the_graded_date(
    clean_engine: AsyncEngine,
) -> None:
    """A retried completion must not push back a review the learner already graded."""
    async with _harness(clean_engine) as harness:
        await harness.login()
        session_id = await _finish_session(harness)
        await _fall_due(harness)
        graded = await harness.client.post(
            "/api/review/complete",
            json={"learning_path_id": EP1.id, "topic": TOPIC, "self_rating": GOOD},
            headers=harness.csrf_headers(),
        )
        graded_at = graded.json()["schedule"]["next_review_at"]

        await _complete(harness, session_id)

        after = await _next_review_at(harness)
    assert after == datetime.fromisoformat(graded_at)


async def test_finishing_a_topic_again_starts_its_spacing_over(
    clean_engine: AsyncEngine,
) -> None:
    async with _harness(clean_engine) as harness:
        await harness.login()
        await _finish_session(harness)
        await _fall_due(harness)
        await harness.client.post(
            "/api/review/complete",
            json={"learning_path_id": EP1.id, "topic": TOPIC, "self_rating": 4},
            headers=harness.csrf_headers(),
        )

        await _finish_session(harness)

        restarted = await _next_review_at(harness)
    assert restarted is not None
    _assert_close(restarted, datetime.now(UTC) + timedelta(days=1))


async def test_a_synced_exam_pulls_a_later_review_forward(
    clean_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The browser's deadline sync compresses reviews as `sophia deadlines sync` does.

    The exam row is seeded rather than fetched: TUWEL is not what is under test.
    """

    async def no_new_deadlines(_app: object, _db: object) -> list[Deadline]:
        return []

    monkeypatch.setattr(deadlines_router, "sync_deadlines", no_new_deadlines)
    exam_at = datetime.now(UTC) + timedelta(days=10)
    async with _harness(clean_engine) as harness:
        async with harness.seed() as session:
            await session.execute(
                insert(review_schedule).values(
                    topic=TOPIC,
                    course_id=EP1.id,
                    next_review_at=datetime.now(UTC) + timedelta(days=20),
                )
            )
            await session.execute(
                insert(deadline_cache).values(
                    id=f"exam:{EP1.id}",
                    name="EP1 Prüfung",
                    course_id=EP1.id,
                    course_name=EP1.fullname,
                    deadline_type="exam",
                    due_at=exam_at.isoformat(),
                )
            )
        await harness.login()

        synced = await harness.client.post("/api/deadlines/sync", headers=harness.csrf_headers())

        compressed = await _next_review_at(harness)
    assert synced.status_code == 200, synced.text
    assert compressed is not None
    _assert_close(compressed, exam_at - timedelta(days=1))


async def test_grading_before_an_exam_does_not_schedule_past_it(
    clean_engine: AsyncEngine,
) -> None:
    exam_at = datetime.now(UTC) + timedelta(days=3)
    async with _harness(clean_engine) as harness:
        async with harness.seed() as session:
            await session.execute(
                insert(deadline_cache).values(
                    id=f"exam:{EP1.id}",
                    name="EP1 Prüfung",
                    course_id=EP1.id,
                    course_name=EP1.fullname,
                    deadline_type="exam",
                    due_at=exam_at.isoformat(),
                )
            )
        await harness.login()
        await _finish_session(harness)
        await _fall_due(harness)
        await _select(harness, GDS)

        # "Easy" from a fresh schedule would come back later than the exam.
        graded = await harness.client.post(
            "/api/review/complete",
            json={"learning_path_id": EP1.id, "topic": TOPIC, "self_rating": 4},
            headers=harness.csrf_headers(),
        )

    assert graded.status_code == 200, graded.text
    _, _, uncapped_days = compute_fsrs_interval(
        FSRS_DEFAULT_DIFFICULTY, FSRS_DEFAULT_STABILITY, SELF_RATING_SCORES[4]
    )
    exam_buffer = exam_at - timedelta(days=1)
    assert datetime.now(UTC) + timedelta(days=uncapped_days) > exam_buffer
    assert datetime.fromisoformat(graded.json()["schedule"]["next_review_at"]) <= exam_buffer
