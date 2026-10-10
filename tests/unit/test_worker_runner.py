"""The worker loop: stage groups per module, in order, with failures recorded (#128)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import insert, select

from sophia.infra.schema import ingestion_jobs, ingestion_workers, lecture_modules
from sophia.services.ingestion_jobs import heartbeat, request_ingestion
from sophia.worker.capability import WorkerCapability
from sophia.worker.runner import NO_MODULES_REASON, StageOutcome, run_worker

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

pytestmark = pytest.mark.postgres

EP1 = 82774
CAPABLE = WorkerCapability(True, gpu_name="GTX 1070")


async def _seed(db: AsyncSession, *, modules: tuple[int, ...] = (3022060, 3022498)) -> int:
    for module_id in modules:
        await db.execute(insert(lecture_modules).values(module_id=module_id, course_id=str(EP1)))
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
        "EmbeddingError: no kernel image is available"
    )


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


def _settings(engine: AsyncEngine):
    from sophia.config import Settings

    return Settings(database_url=engine.url.render_as_string(hide_password=False))
