"""The worker loop — heartbeat, claim a job, run its modules stage group by stage group.

The loop never touches the GPU itself. Each stage group of each module runs
in a child process (see :mod:`sophia.worker.stage`), with the knowledge group
given no CUDA device at all, so Whisper and PyTorch never share a process.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import socket
import sys
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from sophia.config import Settings
from sophia.infra.alembic_runner import upgrade_async
from sophia.infra.engine import create_engine, create_session_factory, session_scope
from sophia.infra.schema import lecture_modules
from sophia.services.ingestion_jobs import (
    claim_next_job,
    fail_orphaned_jobs,
    finish_job,
    heartbeat,
    mark_progress,
)
from sophia.worker.capability import WorkerCapability, probe_capability
from sophia.worker.stage import KNOWLEDGE, MEDIA, STAGE_GROUPS

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from sophia.services.ingestion_jobs import IngestionJob

log = structlog.get_logger()

DEFAULT_POLL_INTERVAL_S = 5.0
# How much of a failed stage's output the job's error keeps: the end of a
# traceback is where the reason is.
ERROR_TAIL_CHARS = 1500
NO_MODULES_REASON = (
    "No lecture recordings are known for this course yet — scan for new lectures first"
)
WORKER_STOPPED_REASON = "The processing worker was stopped before this job finished"


@dataclass(frozen=True, slots=True)
class StageOutcome:
    returncode: int
    output_tail: str


type StageRunner = Callable[[str, int, int, int], Awaitable[StageOutcome]]


# The stage child in flight, so a SIGTERM to the worker reaches it too: a
# container stop must not leave Whisper running on the GPU behind it.
_current_stage: asyncio.subprocess.Process | None = None


async def run_stage_in_subprocess(
    group: str, module_id: int, course_id: int, job_id: int
) -> StageOutcome:
    """``sophia worker stage`` in a child, with the GPU hidden from the knowledge group."""
    global _current_stage
    env = dict(os.environ)
    if group == KNOWLEDGE:
        env["CUDA_VISIBLE_DEVICES"] = ""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "sophia",
        "worker",
        "stage",
        group,
        str(module_id),
        "--course-id",
        str(course_id),
        "--job-id",
        str(job_id),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert process.stdout is not None
    _current_stage = process
    tail = ""
    try:
        async for raw in process.stdout:
            line = raw.decode("utf-8", errors="replace")
            sys.stdout.write(line)
            tail = (tail + line)[-ERROR_TAIL_CHARS:]
        returncode = await process.wait()
    finally:
        _current_stage = None
    return StageOutcome(returncode, tail.strip())


def _install_stop_handlers(stop: asyncio.Event) -> None:
    """Stop on SIGTERM and SIGINT.

    As PID 1 of its container the worker gets no default handler, so without
    this a `docker stop` waits out the grace period and then kills it — and
    the harness that tears the proof stack down had already given up by then.
    """
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        stop.set()
        if _current_stage is not None and _current_stage.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                _current_stage.terminate()

    for signum in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(signum, request_stop)


def default_worker_id() -> str:
    """Unique per process start, not per host and pid.

    As PID 1 of its container every restart would be ``<host>:1`` again, and a
    restarted worker heartbeating under the dead one's id would keep that
    worker's unfinished job "running" for good.
    """
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


async def run_worker(
    settings: Settings | None = None,
    *,
    worker_id: str | None = None,
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    run_stage: StageRunner = run_stage_in_subprocess,
    capability: WorkerCapability | None = None,
    stop_when_idle: bool = False,
    stop: asyncio.Event | None = None,
) -> int:
    """Poll for jobs until stopped. Returns the number of jobs run.

    ``stop_when_idle`` returns as soon as the queue is empty, for tests and
    for a one-shot run; the service keeps polling until ``stop`` is set,
    which SIGTERM and SIGINT do.
    """
    settings = settings or Settings()
    worker_id = worker_id or default_worker_id()
    capability = capability or probe_capability(settings)
    stop = stop or asyncio.Event()
    _install_stop_handlers(stop)
    if capability.capable:
        log.info("worker_started", worker_id=worker_id, gpu=capability.gpu_name)
    else:
        log.error("worker_cannot_process", worker_id=worker_id, reason=capability.reason)

    await upgrade_async(settings.database_url)
    engine = create_engine(settings.database_url, pool_size=2, max_overflow=2)
    factory = create_session_factory(engine)
    processed = 0
    try:
        while not stop.is_set():
            job = await _poll(factory, worker_id, capability, settings)
            if job is None:
                if stop_when_idle:
                    break
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), poll_interval_s)
                continue
            await _run_job(factory, job, run_stage, stop)
            processed += 1
    finally:
        await engine.dispose()
    log.info("worker_stopped", worker_id=worker_id, jobs=processed)
    return processed


async def _poll(
    factory: async_sessionmaker[AsyncSession],
    worker_id: str,
    capability: WorkerCapability,
    settings: Settings,
) -> IngestionJob | None:
    async with session_scope(factory) as session:
        await heartbeat(
            session,
            worker_id,
            hostname=socket.gethostname(),
            capable=capability.capable,
            reason=capability.reason,
            gpu_name=capability.gpu_name,
        )
        await fail_orphaned_jobs(session, stale_after_s=settings.ingestion_worker_stale_seconds)
        if not capability.capable:
            return None
        return await claim_next_job(session, worker_id)


async def _run_job(
    factory: async_sessionmaker[AsyncSession],
    job: IngestionJob,
    run_stage: StageRunner,
    stop: asyncio.Event,
) -> None:
    """Every module of the course, both stage groups each; a failure costs one module.

    A module whose stage failed is left there, with its error, and the next
    module still runs: one bad lecture must not sink the rest of the course.
    The job is marked failed with every module's error at the end, so the
    reason stays visible and a retry is one press away.
    """
    async with session_scope(factory) as session:
        modules = list(
            await session.scalars(
                select(lecture_modules.c.module_id)
                .where(lecture_modules.c.course_id == str(job.course_id))
                .order_by(lecture_modules.c.module_id)
            )
        )
    if not modules:
        await _finish(factory, job.id, NO_MODULES_REASON)
        return

    errors: list[str] = []
    for module_id in modules:
        for group in STAGE_GROUPS:
            if stop.is_set():
                errors.append(WORKER_STOPPED_REASON)
                await _finish(factory, job.id, "; ".join(errors))
                return
            async with session_scope(factory) as session:
                await mark_progress(session, job.id, stage=group, module_id=module_id)
            outcome = await run_stage(group, module_id, job.course_id, job.id)
            if outcome.returncode != 0:
                errors.append(
                    f"{_group_name(group)} failed for recordings {module_id} "
                    f"(exit {outcome.returncode}): {outcome.output_tail}"
                )
                break
    await _finish(factory, job.id, "; ".join(errors) if errors else None)


async def _finish(
    factory: async_sessionmaker[AsyncSession], job_id: int, error: str | None
) -> None:
    async with session_scope(factory) as session:
        await finish_job(session, job_id, error=error)


def _group_name(group: str) -> str:
    return "Download and transcription" if group == MEDIA else "Indexing and topics"
