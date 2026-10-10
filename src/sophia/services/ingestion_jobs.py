"""The queue between the API and the processing worker (#128).

The API inserts a queued job when a learner presses Process, when a scan or
the nightly run finds a subscribed course, and reads the row back for status.
The worker claims the oldest queued job, records the stage and module it is on,
and finishes it. Both sides share only the table, so a job outlives the page
that started it and the API never holds a GPU.

A worker says what it can do in ``ingestion_workers``, refreshed every poll.
A request on a box with no live, capable worker is refused with the reason;
nothing is ever queued for a worker that is not there.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from sophia.domain.errors import IngestionAlreadyRunning, IngestionUnavailable
from sophia.infra.schema import ingestion_jobs, ingestion_workers
from sophia.services.ingestion_settings import subscribed_course_ids

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy import Row
    from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

QUEUED = "queued"
RUNNING = "running"
COMPLETED = "completed"
FAILED = "failed"
ACTIVE_STATUSES = (QUEUED, RUNNING)

NO_WORKER_REASON = "No processing worker is running — start the worker service"
WORKER_GONE_REASON = "The processing worker went away before this job finished"

DEFAULT_WORKER_STALE_S = 90


@dataclass(frozen=True, slots=True)
class IngestionJob:
    id: int
    course_id: int
    status: str
    requested_by: str
    stage: str | None
    module_id: int | None
    error: str | None
    worker_id: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class WorkerAvailability:
    """Whether a live worker can take a job, and if not, why."""

    available: bool
    reason: str = ""
    gpu_name: str = ""


async def worker_availability(
    session: AsyncSession,
    *,
    stale_after_s: int = DEFAULT_WORKER_STALE_S,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> WorkerAvailability:
    """The best live worker's word on whether processing is possible here."""
    seen_since = now() - timedelta(seconds=stale_after_s)
    rows = (
        await session.execute(
            select(
                ingestion_workers.c.capable,
                ingestion_workers.c.reason,
                ingestion_workers.c.gpu_name,
            )
            .where(ingestion_workers.c.last_seen_at >= seen_since)
            .order_by(ingestion_workers.c.capable.desc(), ingestion_workers.c.last_seen_at.desc())
        )
    ).all()
    if not rows:
        return WorkerAvailability(False, NO_WORKER_REASON)
    best = rows[0]
    if best.capable:
        return WorkerAvailability(True, gpu_name=best.gpu_name)
    return WorkerAvailability(False, best.reason or "The processing worker cannot process")


async def request_ingestion(
    session: AsyncSession,
    course_id: int,
    *,
    requested_by: str = "student",
    stale_after_s: int = DEFAULT_WORKER_STALE_S,
) -> IngestionJob:
    """Queue a job for the course, or say why not.

    Raises :class:`IngestionUnavailable` when no live worker can process, and
    :class:`IngestionAlreadyRunning` when the course already has a job that
    has not finished — the second press of Process starts nothing.
    """
    availability = await worker_availability(session, stale_after_s=stale_after_s)
    if not availability.available:
        raise IngestionUnavailable(availability.reason)
    active = await active_job(session, course_id)
    if active is not None:
        raise IngestionAlreadyRunning(active.id)
    try:
        async with session.begin_nested():
            row = (
                await session.execute(
                    insert(ingestion_jobs)
                    .values(course_id=course_id, requested_by=requested_by)
                    .returning(ingestion_jobs)
                )
            ).one()
    except IntegrityError:
        # The partial unique index caught a request racing this one.
        raced = await active_job(session, course_id)
        raise IngestionAlreadyRunning(raced.id if raced else 0) from None
    log.info("ingestion_requested", job_id=row.id, course_id=course_id, requested_by=requested_by)
    return _row_to_job(row)


async def active_job(session: AsyncSession, course_id: int) -> IngestionJob | None:
    row = (
        await session.execute(
            select(ingestion_jobs)
            .where(
                ingestion_jobs.c.course_id == course_id,
                ingestion_jobs.c.status.in_(ACTIVE_STATUSES),
            )
            .order_by(ingestion_jobs.c.created_at.desc())
            .limit(1)
        )
    ).one_or_none()
    return None if row is None else _row_to_job(row)


async def latest_job(session: AsyncSession, course_id: int) -> IngestionJob | None:
    """The job to show for the course: the active one, else the last finished."""
    row = (
        await session.execute(
            select(ingestion_jobs)
            .where(ingestion_jobs.c.course_id == course_id)
            .order_by(ingestion_jobs.c.created_at.desc(), ingestion_jobs.c.id.desc())
            .limit(1)
        )
    ).one_or_none()
    return None if row is None else _row_to_job(row)


async def enqueue_subscribed(
    session: AsyncSession,
    *,
    requested_by: str,
    stale_after_s: int = DEFAULT_WORKER_STALE_S,
) -> list[int]:
    """Queue every subscribed course that has no job in flight.

    Returns the course ids queued. With no worker to take them nothing is
    queued and the reason is logged once: a scan that found new recordings
    still succeeded, and a job nobody can run is not progress.
    """
    courses = await subscribed_course_ids(session)
    if not courses:
        return []
    availability = await worker_availability(session, stale_after_s=stale_after_s)
    if not availability.available:
        log.warning(
            "ingestion_subscriptions_skipped",
            requested_by=requested_by,
            courses=courses,
            reason=availability.reason,
        )
        return []
    queued: list[int] = []
    for course_id in courses:
        try:
            await request_ingestion(
                session, course_id, requested_by=requested_by, stale_after_s=stale_after_s
            )
        except IngestionAlreadyRunning:
            continue
        queued.append(course_id)
    log.info("ingestion_subscriptions_queued", requested_by=requested_by, courses=queued)
    return queued


# --- the worker's side ---------------------------------------------------------


async def heartbeat(
    session: AsyncSession,
    worker_id: str,
    *,
    hostname: str,
    capable: bool,
    reason: str,
    gpu_name: str,
) -> None:
    now = datetime.now(UTC)
    statement = pg_insert(ingestion_workers).values(
        worker_id=worker_id,
        hostname=hostname,
        capable=capable,
        reason=reason,
        gpu_name=gpu_name,
        started_at=now,
        last_seen_at=now,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[ingestion_workers.c.worker_id],
            set_={
                "hostname": statement.excluded.hostname,
                "capable": statement.excluded.capable,
                "reason": statement.excluded.reason,
                "gpu_name": statement.excluded.gpu_name,
                "last_seen_at": statement.excluded.last_seen_at,
            },
        )
    )


async def claim_next_job(session: AsyncSession, worker_id: str) -> IngestionJob | None:
    """Take the oldest queued job, so two workers never run the same one."""
    oldest = (
        select(ingestion_jobs.c.id)
        .where(ingestion_jobs.c.status == QUEUED)
        .order_by(ingestion_jobs.c.created_at, ingestion_jobs.c.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    row = (
        await session.execute(
            update(ingestion_jobs)
            .where(ingestion_jobs.c.id == oldest)
            .values(status=RUNNING, worker_id=worker_id, started_at=datetime.now(UTC))
            .returning(ingestion_jobs)
        )
    ).one_or_none()
    if row is None:
        return None
    log.info("ingestion_job_claimed", job_id=row.id, course_id=row.course_id, worker=worker_id)
    return _row_to_job(row)


async def mark_progress(
    session: AsyncSession,
    job_id: int,
    *,
    stage: str | None = None,
    module_id: int | None = None,
) -> None:
    values: dict[str, object] = {}
    if stage is not None:
        values["stage"] = stage
    if module_id is not None:
        values["module_id"] = module_id
    if values:
        await session.execute(
            update(ingestion_jobs).where(ingestion_jobs.c.id == job_id).values(**values)
        )


async def finish_job(session: AsyncSession, job_id: int, *, error: str | None = None) -> None:
    await session.execute(
        update(ingestion_jobs)
        .where(ingestion_jobs.c.id == job_id)
        .values(
            status=FAILED if error else COMPLETED,
            error=error,
            finished_at=datetime.now(UTC),
        )
    )
    if error:
        log.error("ingestion_job_failed", job_id=job_id, error=error)
    else:
        log.info("ingestion_job_completed", job_id=job_id)


async def fail_orphaned_jobs(
    session: AsyncSession,
    *,
    stale_after_s: int = DEFAULT_WORKER_STALE_S,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[int]:
    """Mark running jobs whose worker has stopped reporting as failed.

    A worker killed mid-job leaves its row running forever otherwise, and
    "one job per course" would then refuse every later request.
    """
    live = select(ingestion_workers.c.worker_id).where(
        ingestion_workers.c.last_seen_at >= now() - timedelta(seconds=stale_after_s)
    )
    rows = (
        await session.execute(
            update(ingestion_jobs)
            .where(
                ingestion_jobs.c.status == RUNNING,
                ingestion_jobs.c.worker_id.not_in(live),
            )
            .values(status=FAILED, error=WORKER_GONE_REASON, finished_at=now())
            .returning(ingestion_jobs.c.id)
        )
    ).all()
    orphaned = [row.id for row in rows]
    if orphaned:
        log.warning("ingestion_jobs_orphaned", job_ids=orphaned)
    return orphaned


def _row_to_job(row: Row[Any]) -> IngestionJob:
    return IngestionJob(
        id=row.id,
        course_id=row.course_id,
        status=row.status,
        requested_by=row.requested_by,
        stage=row.stage,
        module_id=row.module_id,
        error=row.error,
        worker_id=row.worker_id,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )
