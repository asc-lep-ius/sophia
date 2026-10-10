"""The queue between the API and the processing worker (#128)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from sophia.domain.errors import IngestionAlreadyRunning, IngestionUnavailable
from sophia.services.ingestion_jobs import (
    NO_WORKER_REASON,
    WORKER_GONE_REASON,
    active_job,
    claim_next_job,
    enqueue_subscribed,
    fail_orphaned_jobs,
    finish_job,
    heartbeat,
    latest_job,
    mark_progress,
    request_ingestion,
    worker_availability,
)
from sophia.services.ingestion_settings import IngestionSettings, save_ingestion_settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

EP1 = 82774
GDS = 83629


async def _worker(
    db: AsyncSession, worker_id: str = "hephaestus:1", *, capable: bool = True, reason: str = ""
) -> None:
    await heartbeat(
        db, worker_id, hostname="hephaestus", capable=capable, reason=reason, gpu_name="GTX 1070"
    )


async def test_process_is_refused_with_the_reason_when_no_worker_is_running(
    db: AsyncSession,
) -> None:
    with pytest.raises(IngestionUnavailable) as refused:
        await request_ingestion(db, EP1)

    assert refused.value.params == {"reason": NO_WORKER_REASON}
    assert await active_job(db, EP1) is None


async def test_process_is_refused_with_the_workers_own_reason(db: AsyncSession) -> None:
    """Scenario: no GPU — refused with that reason, never a silent failure."""
    await _worker(db, capable=False, reason="No usable NVIDIA GPU: nvidia-smi found none")

    with pytest.raises(IngestionUnavailable) as refused:
        await request_ingestion(db, EP1)

    assert refused.value.params["reason"] == "No usable NVIDIA GPU: nvidia-smi found none"


async def test_a_stale_heartbeat_counts_as_no_worker(db: AsyncSession) -> None:
    await _worker(db)
    later = datetime.now(UTC) + timedelta(seconds=200)

    availability = await worker_availability(db, now=lambda: later)

    assert (availability.available, availability.reason) == (False, NO_WORKER_REASON)


async def test_one_job_per_course(db: AsyncSession) -> None:
    """Scenario: pressing Process again starts nothing and says it is already running."""
    await _worker(db)
    first = await request_ingestion(db, EP1)

    with pytest.raises(IngestionAlreadyRunning) as refused:
        await request_ingestion(db, EP1)

    assert refused.value.params == {"job_id": first.id}
    assert first.status == "queued"
    # Another course is not blocked by it.
    assert (await request_ingestion(db, GDS)).course_id == GDS


async def test_the_worker_claims_the_oldest_job_and_finishes_it(db: AsyncSession) -> None:
    await _worker(db)
    first = await request_ingestion(db, EP1)
    await request_ingestion(db, GDS)

    claimed = await claim_next_job(db, "hephaestus:1")
    assert claimed is not None
    assert (claimed.id, claimed.status, claimed.worker_id) == (first.id, "running", "hephaestus:1")
    await mark_progress(db, claimed.id, stage="transcribe", module_id=3022060)
    shown = await latest_job(db, EP1)
    assert shown is not None and (shown.stage, shown.module_id) == ("transcribe", 3022060)

    await finish_job(db, claimed.id)
    done = await latest_job(db, EP1)
    assert done is not None and done.status == "completed" and done.finished_at is not None
    # The course can be processed again once its job has finished.
    assert (await request_ingestion(db, EP1)).id != first.id


async def test_a_failed_job_keeps_its_reason(db: AsyncSession) -> None:
    await _worker(db)
    job = await request_ingestion(db, EP1)
    await claim_next_job(db, "hephaestus:1")

    await finish_job(db, job.id, error="Indexing and topics failed: no kernel image")

    failed = await latest_job(db, EP1)
    assert failed is not None
    assert (failed.status, failed.error) == (
        "failed",
        "Indexing and topics failed: no kernel image",
    )


async def test_a_job_whose_worker_went_away_is_failed_not_left_running(db: AsyncSession) -> None:
    await _worker(db)
    job = await request_ingestion(db, EP1)
    await claim_next_job(db, "hephaestus:1")
    later = datetime.now(UTC) + timedelta(seconds=200)

    assert await fail_orphaned_jobs(db, now=lambda: later) == [job.id]

    failed = await latest_job(db, EP1)
    assert failed is not None and (failed.status, failed.error) == ("failed", WORKER_GONE_REASON)


async def test_subscribed_courses_are_queued_and_unsubscribed_ones_are_not(
    db: AsyncSession,
) -> None:
    """Scenarios: new recordings follow a subscribed course; unsubscribing stops that."""
    await _worker(db)
    await save_ingestion_settings(db, IngestionSettings(course_id=EP1, subscribed=True))
    await save_ingestion_settings(db, IngestionSettings(course_id=GDS, subscribed=False))

    assert await enqueue_subscribed(db, requested_by="scan") == [EP1]
    queued = await active_job(db, EP1)
    assert queued is not None and queued.requested_by == "scan"
    assert await active_job(db, GDS) is None
    # A course already in flight is not queued twice.
    assert await enqueue_subscribed(db, requested_by="nightly") == []

    await save_ingestion_settings(db, IngestionSettings(course_id=EP1, subscribed=False))
    await finish_job(db, queued.id)
    assert await enqueue_subscribed(db, requested_by="nightly") == []


async def test_nothing_is_queued_for_subscriptions_without_a_worker(db: AsyncSession) -> None:
    await save_ingestion_settings(db, IngestionSettings(course_id=EP1, subscribed=True))

    assert await enqueue_subscribed(db, requested_by="scan") == []
    assert await active_job(db, EP1) is None


async def test_a_request_fails_a_stranded_job_and_queues_anew(db: AsyncSession) -> None:
    """A job whose worker died must not answer "already running" for good."""
    from sqlalchemy import select, update

    from sophia.infra.schema import ingestion_jobs, ingestion_workers

    await _worker(db, "hephaestus:1:dead")
    stranded = await request_ingestion(db, EP1)
    await claim_next_job(db, "hephaestus:1:dead")
    # The dead worker stops heartbeating; a restarted one reports under a new id.
    await db.execute(
        update(ingestion_workers)
        .where(ingestion_workers.c.worker_id == "hephaestus:1:dead")
        .values(last_seen_at=datetime.now(UTC) - timedelta(hours=1))
    )
    await _worker(db, "hephaestus:1:new")

    fresh = await request_ingestion(db, EP1)

    assert fresh.id != stranded.id
    status = await db.scalar(
        select(ingestion_jobs.c.status).where(ingestion_jobs.c.id == stranded.id)
    )
    assert status == "failed"


async def test_a_job_failed_as_orphaned_keeps_that_outcome(db: AsyncSession) -> None:
    """A worker's late finish must not overwrite what the sweep recorded."""
    await _worker(db)
    job = await request_ingestion(db, EP1)
    await claim_next_job(db, "hephaestus:1")
    later = datetime.now(UTC) + timedelta(seconds=200)
    assert await fail_orphaned_jobs(db, now=lambda: later) == [job.id]

    await finish_job(db, job.id)

    shown = await latest_job(db, EP1)
    assert shown is not None and (shown.status, shown.error) == ("failed", WORKER_GONE_REASON)
