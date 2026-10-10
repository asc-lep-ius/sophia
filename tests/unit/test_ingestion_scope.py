"""Which recordings a job covers: the course's own semester, or the older ones on request (#128)."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import insert, select, update

from sophia.domain.models import Lecture
from sophia.infra.schema import (
    lecture_downloads,
    lecture_modules,
    lecture_recordings,
    topic_extractions,
    transcriptions,
)
from sophia.services.ingestion_scope import (
    CURRENT_SEMESTER,
    OLDER,
    course_semester,
    older_recordings_pending,
    register_recordings,
    scoped_episode_ids,
    semester_window,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

EP1 = 82774
MODULE = 3022060
OLD_SERIES = 3022498


@pytest.mark.parametrize(
    ("semester", "window"),
    [
        ("2026W", (date(2026, 10, 1), date(2027, 2, 28))),
        ("2027W", (date(2027, 10, 1), date(2028, 2, 29))),
        ("2026S", (date(2026, 3, 1), date(2026, 9, 30))),
        ("2026", None),
        ("WS2026", None),
    ],
)
def test_semester_windows_follow_ug_52(semester: str, window: tuple[date, date] | None) -> None:
    assert semester_window(semester) == window


async def _course(db: AsyncSession, *, shortname: str = "185.A91-2026W", name: str = "") -> None:
    for module_id in (MODULE, OLD_SERIES):
        await db.execute(
            insert(lecture_modules).values(
                module_id=module_id,
                course_id=str(EP1),
                course_shortname=shortname,
                course_name=name,
            )
        )


def _lecture(episode_id: str, created: str) -> Lecture:
    return Lecture(episode_id=episode_id, title=episode_id, series_id="", created=created)


async def _register(db: AsyncSession) -> None:
    await register_recordings(
        db,
        MODULE,
        [_lecture("ep-oct", "2026-10-09"), _lecture("ep-undated", "")],
        course_id=str(EP1),
    )
    await register_recordings(
        db, OLD_SERIES, [_lecture("ep-jun", "2026-06-15")], course_id=str(EP1)
    )


async def test_the_semester_is_read_from_the_modules_discovery_recorded(db: AsyncSession) -> None:
    await _course(db, shortname="EP1", name="185.A91 Einführung in die Programmierung 1 2026W")

    assert await course_semester(db, EP1) == "2026W"
    assert await course_semester(db, 1) is None


async def test_a_semester_job_covers_the_dated_and_undated_current_recordings_only(
    db: AsyncSession,
) -> None:
    await _course(db)
    await _register(db)

    assert await scoped_episode_ids(db, EP1, MODULE, CURRENT_SEMESTER) == {"ep-oct", "ep-undated"}
    assert await scoped_episode_ids(db, EP1, OLD_SERIES, CURRENT_SEMESTER) == frozenset()
    assert await scoped_episode_ids(db, EP1, MODULE, OLDER) == frozenset()
    assert await scoped_episode_ids(db, EP1, OLD_SERIES, OLDER) == {"ep-jun"}
    # Nothing registered yet: the media stage has to list the series first.
    assert await scoped_episode_ids(db, EP1, 999, CURRENT_SEMESTER) is None


async def test_registering_again_keeps_a_date_the_page_no_longer_shows(db: AsyncSession) -> None:
    await _course(db)
    await _register(db)

    await register_recordings(db, MODULE, [_lecture("ep-oct", "")], course_id=str(EP1))

    recorded_on = await db.scalar(
        select(lecture_recordings.c.recorded_on).where(lecture_recordings.c.episode_id == "ep-oct")
    )
    assert recorded_on == date(2026, 10, 9)


async def test_older_recordings_are_pending_until_their_topics_exist_or_settled(
    db: AsyncSession,
) -> None:
    """A transcript alone leaves an older lecture pending: its topics may still have failed."""
    await _course(db)
    await _register(db)
    assert await older_recordings_pending(db, EP1) == 1

    await db.execute(
        insert(transcriptions).values(episode_id="ep-jun", module_id=OLD_SERIES, status="completed")
    )
    assert await older_recordings_pending(db, EP1) == 1
    await db.execute(
        insert(topic_extractions).values(
            episode_id="ep-jun", course_id=EP1, status="failed", error="503 UNAVAILABLE"
        )
    )
    assert await older_recordings_pending(db, EP1) == 1
    await db.execute(
        update(topic_extractions)
        .where(topic_extractions.c.episode_id == "ep-jun")
        .values(status="completed", topic_count=3, error=None)
    )
    assert await older_recordings_pending(db, EP1) == 0

    await register_recordings(db, OLD_SERIES, [_lecture("ep-silent", "2026-05-04")])
    assert await older_recordings_pending(db, EP1) == 1
    await db.execute(
        insert(lecture_downloads).values(
            episode_id="ep-silent",
            module_id=OLD_SERIES,
            title="silent",
            track_url="u",
            track_mimetype="audio/mp4",
            status="skipped",
            skip_reason="silent_recording",
        )
    )
    assert await older_recordings_pending(db, EP1) == 0


async def test_without_a_semester_every_recording_is_current(db: AsyncSession) -> None:
    await _course(db, shortname="EP1", name="Einführung in die Programmierung 1")
    await _register(db)

    assert await scoped_episode_ids(db, EP1, OLD_SERIES, CURRENT_SEMESTER) == {"ep-jun"}
    assert await scoped_episode_ids(db, EP1, OLD_SERIES, OLDER) == frozenset()
    assert await older_recordings_pending(db, EP1) == 0


async def test_the_media_stage_child_lists_the_series_before_reading_the_scope(
    db: AsyncSession,
) -> None:
    """The media group registers the series page first; the knowledge group reads what it left."""
    from unittest.mock import AsyncMock, MagicMock

    from sophia.services.ingestion_jobs import heartbeat, request_ingestion
    from sophia.worker.stage import KNOWLEDGE, MEDIA, _job_scope

    await _course(db)
    await heartbeat(db, "w", hostname="x", capable=True, reason="", gpu_name="GTX 1070")
    job = await request_ingestion(db, EP1, scope=OLDER)
    container = MagicMock()
    container.opencast.get_series_episodes = AsyncMock(
        return_value=[_lecture("ep-oct", "2026-10-09"), _lecture("ep-jun", "2026-06-15")]
    )

    unknown_before = await _job_scope(container, db, KNOWLEDGE, OLD_SERIES, EP1, job.id)
    media = await _job_scope(container, db, MEDIA, OLD_SERIES, EP1, job.id)
    knowledge = await _job_scope(container, db, KNOWLEDGE, OLD_SERIES, EP1, job.id)
    # No job row at all reads as a semester job.
    no_job = await _job_scope(container, db, KNOWLEDGE, OLD_SERIES, EP1, job.id + 1)

    assert unknown_before is None
    assert media == {"ep-jun"}
    assert knowledge == {"ep-jun"}
    assert no_job == {"ep-oct"}
    container.opencast.get_series_episodes.assert_awaited_once_with(OLD_SERIES)


async def test_the_stage_child_hands_both_stage_groups_the_jobs_scope(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plain Process on a module whose series mixes semesters must never hand the
    older recordings to the media or the knowledge stages: that is the GPU time the
    semester rule exists to save."""
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock, MagicMock

    from sophia.services.hermes_pipeline import PipelineResult
    from sophia.services.ingestion_jobs import heartbeat, request_ingestion
    from sophia.worker import stage

    await _course(db)
    await heartbeat(db, "w", hostname="x", capable=True, reason="", gpu_name="GTX 1070")
    job = await request_ingestion(db, EP1, scope=CURRENT_SEMESTER)
    container = MagicMock()
    container.opencast.get_series_episodes = AsyncMock(
        return_value=[_lecture("ep-oct", "2026-10-09"), _lecture("ep-jun", "2026-06-15")]
    )

    @asynccontextmanager
    async def _session():
        yield db

    @asynccontextmanager
    async def _create_app(settings=None):
        yield container

    container.session = _session
    monkeypatch.setattr(stage, "create_app", _create_app)
    media = AsyncMock(return_value=PipelineResult())
    knowledge = AsyncMock(return_value=PipelineResult())
    monkeypatch.setattr(stage, "run_media_stages", media)
    monkeypatch.setattr(stage, "run_knowledge_stages", knowledge)

    await stage.run_stage_group(stage.MEDIA, MODULE, course_id=EP1, job_id=job.id)
    await stage.run_stage_group(stage.KNOWLEDGE, MODULE, course_id=EP1, job_id=job.id)

    assert media.await_args is not None and knowledge.await_args is not None
    assert media.await_args.kwargs["only_episodes"] == {"ep-oct"}
    assert knowledge.await_args.kwargs["only_episodes"] == {"ep-oct"}
    assert knowledge.await_args.kwargs["strict"] is True
