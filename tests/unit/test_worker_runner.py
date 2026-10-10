"""The worker loop: stage groups per module, in order, with failures recorded (#128)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import insert, select

from sophia.infra.engine import create_session_factory
from sophia.infra.schema import ingestion_jobs, ingestion_workers, lecture_modules
from sophia.services.ingestion_jobs import heartbeat, request_ingestion
from sophia.worker.capability import WorkerCapability
from sophia.worker.runner import NO_MODULES_REASON, StageOutcome, run_worker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.postgres

EP1 = 82774
CAPABLE = WorkerCapability(True, gpu_name="GTX 1070")


LAST_SEMESTER = 78417
LAST_SEMESTER_MODULE = 2856855


async def _seed(db: AsyncSession, *, modules: tuple[int, ...] = (3022060, 3022498)) -> int:
    for module_id in modules:
        await db.execute(insert(lecture_modules).values(module_id=module_id, course_id=str(EP1)))
    # Last semester's module, which Process must leave alone unless asked.
    await db.execute(
        insert(lecture_modules).values(module_id=LAST_SEMESTER_MODULE, course_id=str(LAST_SEMESTER))
    )
    await heartbeat(db, "seed", hostname="x", capable=True, reason="", gpu_name="GTX 1070")
    return (await request_ingestion(db, EP1)).id


async def _job_row(engine: AsyncEngine, job_id: int):
    async with engine.connect() as connection:
        return (
            await connection.execute(select(ingestion_jobs).where(ingestion_jobs.c.id == job_id))
        ).one()


async def test_a_job_runs_both_stage_groups_of_every_module_in_order(
    clean_engine: AsyncEngine, db: AsyncSession
) -> None:
    job_id = await _seed(db)
    await db.commit()
    calls: list[tuple[str, int, int, int]] = []

    async def fake_stage(group: str, module_id: int, course_id: int, job: int) -> StageOutcome:
        calls.append((group, module_id, course_id, job))
        return StageOutcome(0, "")

    processed = await run_worker(
        _settings(clean_engine),
        worker_id="test:1",
        run_stage=fake_stage,
        capability=CAPABLE,
        stop_when_idle=True,
    )

    assert processed == 1
    assert calls == [
        ("media", 3022060, EP1, job_id),
        ("knowledge", 3022060, EP1, job_id),
        ("media", 3022498, EP1, job_id),
        ("knowledge", 3022498, EP1, job_id),
    ]
    assert all(module_id != LAST_SEMESTER_MODULE for _, module_id, _, _ in calls)
    row = await _job_row(clean_engine, job_id)
    assert (row.status, row.error, row.worker_id) == ("completed", None, "test:1")
    assert (row.stage, row.module_id) == ("knowledge", 3022498)


async def test_a_failed_stage_marks_the_job_failed_with_the_output_tail(
    clean_engine: AsyncEngine, db: AsyncSession
) -> None:
    job_id = await _seed(db)
    await db.commit()

    async def fake_stage(group: str, module_id: int, _course: int, _job: int) -> StageOutcome:
        if group == "knowledge":
            return StageOutcome(1, "EmbeddingError: no kernel image is available")
        return StageOutcome(0, "")

    await run_worker(
        _settings(clean_engine),
        worker_id="test:1",
        run_stage=fake_stage,
        capability=CAPABLE,
        stop_when_idle=True,
    )

    row = await _job_row(clean_engine, job_id)
    assert row.status == "failed"
    assert row.error == (
        "Indexing and topics failed for recordings 3022060 (exit 1): "
        "EmbeddingError: no kernel image is available; "
        "Indexing and topics failed for recordings 3022498 (exit 1): "
        "EmbeddingError: no kernel image is available"
    )


async def test_a_failed_module_does_not_sink_the_rest_of_the_course(
    clean_engine: AsyncEngine, db: AsyncSession
) -> None:
    """Scenario: a failed lecture is marked with its reason and the others are still processed."""
    job_id = await _seed(db)
    await db.commit()
    calls: list[tuple[str, int]] = []

    async def fake_stage(group: str, module_id: int, _course: int, _job: int) -> StageOutcome:
        calls.append((group, module_id))
        if (group, module_id) == ("knowledge", 3022060):
            return StageOutcome(1, "TopicExtractionError: 503 UNAVAILABLE")
        return StageOutcome(0, "")

    await run_worker(
        _settings(clean_engine),
        worker_id="test:1",
        run_stage=fake_stage,
        capability=CAPABLE,
        stop_when_idle=True,
    )

    assert calls == [
        ("media", 3022060),
        ("knowledge", 3022060),
        ("media", 3022498),
        ("knowledge", 3022498),
    ]
    row = await _job_row(clean_engine, job_id)
    assert (row.status, row.error) == (
        "failed",
        "Indexing and topics failed for recordings 3022060 (exit 1): "
        "TopicExtractionError: 503 UNAVAILABLE",
    )


async def test_a_stop_between_stages_fails_the_job_rather_than_starting_the_next(
    clean_engine: AsyncEngine, db: AsyncSession
) -> None:
    import asyncio

    from sophia.worker.runner import WORKER_STOPPED_REASON

    job_id = await _seed(db)
    await db.commit()
    stop = asyncio.Event()
    calls: list[tuple[str, int]] = []

    async def fake_stage(group: str, module_id: int, _course: int, _job: int) -> StageOutcome:
        calls.append((group, module_id))
        stop.set()
        return StageOutcome(0, "")

    await run_worker(
        _settings(clean_engine),
        worker_id="test:1",
        run_stage=fake_stage,
        capability=CAPABLE,
        stop_when_idle=True,
        stop=stop,
    )

    assert calls == [("media", 3022060)]
    row = await _job_row(clean_engine, job_id)
    assert (row.status, row.error) == ("failed", WORKER_STOPPED_REASON)


async def test_a_stage_killed_by_the_stop_is_recorded_as_stopped_not_as_its_last_lines(
    clean_engine: AsyncEngine, db: AsyncSession
) -> None:
    """`docker stop` mid-Whisper must not leave the learner a page of log as the reason."""
    import asyncio

    from sophia.worker.runner import WORKER_STOPPED_REASON

    job_id = await _seed(db)
    await db.commit()
    stop = asyncio.Event()
    calls: list[tuple[str, int]] = []

    async def killed_stage(group: str, module_id: int, _course: int, _job: int) -> StageOutcome:
        calls.append((group, module_id))
        stop.set()
        return StageOutcome(-15, '{"event": "transcript_source", "audio": "/data/x.m4a"}')

    await run_worker(
        _settings(clean_engine),
        worker_id="test:1",
        run_stage=killed_stage,
        capability=CAPABLE,
        stop_when_idle=True,
        stop=stop,
    )

    assert calls == [("media", 3022060)]
    row = await _job_row(clean_engine, job_id)
    assert (row.status, row.error) == ("failed", WORKER_STOPPED_REASON)


def test_the_default_worker_id_is_unique_per_process_start() -> None:
    """PID 1 of a restarted container must not inherit the dead worker's id."""
    from sophia.worker.runner import default_worker_id

    assert default_worker_id() != default_worker_id()


async def test_a_course_with_no_known_recordings_fails_with_a_reason(
    clean_engine: AsyncEngine, db: AsyncSession
) -> None:
    job_id = await _seed(db, modules=())
    await db.commit()

    async def never(*_args: object) -> StageOutcome:
        raise AssertionError("no stage should run")

    await run_worker(
        _settings(clean_engine),
        worker_id="test:1",
        run_stage=never,
        capability=CAPABLE,
        stop_when_idle=True,
    )

    row = await _job_row(clean_engine, job_id)
    assert (row.status, row.error) == ("failed", NO_MODULES_REASON)


async def test_an_incapable_worker_reports_its_reason_and_claims_nothing(
    clean_engine: AsyncEngine, db: AsyncSession
) -> None:
    job_id = await _seed(db)
    await db.commit()

    async def never(*_args: object) -> StageOutcome:
        raise AssertionError("no stage should run")

    processed = await run_worker(
        _settings(clean_engine),
        worker_id="test:1",
        run_stage=never,
        capability=WorkerCapability(False, reason="No usable NVIDIA GPU"),
        stop_when_idle=True,
    )

    assert processed == 0
    assert (await _job_row(clean_engine, job_id)).status == "queued"
    async with clean_engine.connect() as connection:
        worker = (
            await connection.execute(
                select(ingestion_workers).where(ingestion_workers.c.worker_id == "test:1")
            )
        ).one()
    assert (worker.capable, worker.reason) == (False, "No usable NVIDIA GPU")


def _settings(engine: AsyncEngine, *, stale_seconds: int = 90):
    from sophia.config import Settings

    return Settings(
        database_url=engine.url.render_as_string(hide_password=False),
        ingestion_worker_stale_seconds=stale_seconds,
    )


async def test_the_worker_stops_when_asked_even_while_idle(
    clean_engine: AsyncEngine, db: AsyncSession
) -> None:
    """A `docker stop` must not wait out the grace period on a PID 1 that ignores it."""
    import asyncio

    stop = asyncio.Event()

    async def never(*_args: object) -> StageOutcome:
        raise AssertionError("no stage should run")

    worker = asyncio.create_task(
        run_worker(
            _settings(clean_engine),
            worker_id="test:1",
            run_stage=never,
            capability=CAPABLE,
            poll_interval_s=30.0,
            stop=stop,
        )
    )
    await asyncio.sleep(0.5)
    stop.set()

    assert await asyncio.wait_for(worker, timeout=5) == 0


async def test_the_worker_keeps_reporting_in_while_a_job_runs(
    clean_engine: AsyncEngine, db: AsyncSession
) -> None:
    """A job longer than the stale window must not be failed as orphaned mid-run."""
    import asyncio

    from sophia.domain.errors import IngestionAlreadyRunning
    from sophia.infra.engine import session_scope
    from sophia.services.ingestion_jobs import (
        fail_orphaned_jobs,
        request_ingestion,
        worker_availability,
    )

    job_id = await _seed(db)
    await db.commit()
    factory = create_session_factory(clean_engine)
    seen: dict[str, object] = {}

    async def slow_stage(group: str, module_id: int, _course: int, _job: int) -> StageOutcome:
        if (group, module_id) == ("media", 3022060):
            # Longer than the window the checks below use; the heartbeat loop
            # (every stale/3 = 1 s here) is what keeps the worker alive.
            await asyncio.sleep(2.6)
            async with session_scope(factory) as session:
                seen["orphaned"] = await fail_orphaned_jobs(session, stale_after_s=2)
                seen["available"] = (await worker_availability(session, stale_after_s=2)).available
                try:
                    await request_ingestion(session, EP1, stale_after_s=2)
                except IngestionAlreadyRunning as exc:
                    seen["second_press"] = exc.params
        return StageOutcome(0, "")

    await run_worker(
        _settings(clean_engine, stale_seconds=3),
        worker_id="test:1",
        run_stage=slow_stage,
        capability=CAPABLE,
        poll_interval_s=1.0,
        stop_when_idle=True,
    )

    assert seen == {"orphaned": [], "available": True, "second_press": {"job_id": job_id}}
    assert (await _job_row(clean_engine, job_id)).status == "completed"
