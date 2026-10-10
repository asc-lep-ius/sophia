"""One stage group of one module, run in a process of its own.

The worker starts this through ``sophia worker stage`` rather than calling it
in-process, because the two groups cannot share a process on a Pascal GPU:
Whisper needs the GPU, and PyTorch has no kernels for it, so the knowledge
stages run with ``CUDA_VISIBLE_DEVICES`` empty. A stage that raises exits
non-zero, and the worker records the tail of its output as the job's error.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from sophia.infra.di import create_app
from sophia.services.hermes_pipeline import run_knowledge_stages, run_media_stages
from sophia.services.ingestion_jobs import mark_progress

if TYPE_CHECKING:
    from sophia.config import Settings
    from sophia.infra.di import AppContainer
    from sophia.services.hermes_pipeline import PipelineResult

log = structlog.get_logger()

MEDIA = "media"
KNOWLEDGE = "knowledge"
STAGE_GROUPS = (MEDIA, KNOWLEDGE)


class JobProgress:
    """Writes the stage a job is on, from the pipeline's synchronous callbacks.

    Each write opens its own session on the container's pool, so it never
    shares the pipeline's session from another task; the writes are awaited
    before the stage returns.
    """

    def __init__(self, container: AppContainer, job_id: int, module_id: int) -> None:
        self._container = container
        self._job_id = job_id
        self._module_id = module_id
        self._writes: list[asyncio.Task[None]] = []

    def note(self, stage: str) -> None:
        log.info("ingestion_stage", job_id=self._job_id, module_id=self._module_id, stage=stage)
        self._writes.append(asyncio.get_running_loop().create_task(self._write(stage)))

    async def _write(self, stage: str) -> None:
        async with self._container.session() as session:
            await mark_progress(session, self._job_id, stage=stage, module_id=self._module_id)

    async def flush(self) -> None:
        if self._writes:
            await asyncio.gather(*self._writes)
            self._writes.clear()


async def run_stage_group(
    group: str,
    module_id: int,
    *,
    course_id: int,
    job_id: int,
    settings: Settings | None = None,
) -> PipelineResult:
    """Run one stage group for one module inside a freshly built container."""
    if group not in STAGE_GROUPS:
        msg = f"unknown stage group {group!r}; expected one of {', '.join(STAGE_GROUPS)}"
        raise ValueError(msg)

    async with create_app(settings) as container:
        progress = JobProgress(container, job_id, module_id)
        try:
            async with container.session() as session:
                if group == MEDIA:
                    result = await run_media_stages(
                        container, session, module_id, on_stage=progress.note
                    )
                else:
                    result = await run_knowledge_stages(
                        container,
                        session,
                        module_id,
                        course_id=course_id,
                        on_stage=progress.note,
                        strict=True,
                    )
        finally:
            await progress.flush()

    log.info(
        "ingestion_stage_group_done",
        job_id=job_id,
        module_id=module_id,
        group=group,
        downloads=len(result.downloads),
        transcriptions=len(result.transcriptions),
        indexed=len(result.indexing),
        lecture_topics=len(result.lecture_topics),
    )
    return result
