"""Hermes pipeline orchestration — run download → transcribe → index → extract topics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from sophia.services.athena_study import extract_topics_from_lectures
from sophia.services.hermes_download import LectureDownloadResult, download_lectures
from sophia.services.hermes_index import IndexingResult, index_lectures
from sophia.services.hermes_manage import assign_lecture_numbers
from sophia.services.hermes_transcribe import TranscriptionResult, transcribe_lectures

if TYPE_CHECKING:
    from collections.abc import Callable

    from sophia.domain.models import DownloadProgressEvent, TopicMapping
    from sophia.infra.di import AppContainer

log = structlog.get_logger()


@dataclass
class PipelineResult:
    """Aggregated outcome of the full lecture pipeline."""

    downloads: list[LectureDownloadResult] = field(default_factory=lambda: [])
    transcriptions: list[TranscriptionResult] = field(default_factory=lambda: [])
    indexing: list[IndexingResult] = field(default_factory=lambda: [])
    topics: list[TopicMapping] = field(default_factory=lambda: [])
    material_chunks: int = 0
    cancelled: bool = False


async def run_pipeline(
    app: AppContainer,
    module_id: int,
    *,
    episode_ids: set[str] | None = None,
    index_materials: bool = False,
    course_id: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_download_progress: Callable[[str, DownloadProgressEvent], None] | None = None,
    on_transcribe_start: Callable[[str, str], None] | None = None,
    on_transcribe_complete: Callable[[str, int], None] | None = None,
    on_index_start: Callable[[str, str], None] | None = None,
    on_index_complete: Callable[[str, int], None] | None = None,
    on_topic_progress: Callable[[str], None] | None = None,
) -> PipelineResult:
    """Orchestrate the full lecture pipeline for a module.

    Stages run sequentially: download → transcribe → index → extract topics.
    Each stage handles per-episode failures internally — a single episode failure
    does not abort the pipeline.
    """
    result = PipelineResult()

    log.info("pipeline_start", module_id=module_id)

    if cancel_check and cancel_check():
        log.info("pipeline_cancelled", module_id=module_id, stage="before_download")
        result.cancelled = True
        return result

    result.downloads = await download_lectures(
        app,
        module_id,
        episode_ids=episode_ids,
        on_progress=on_download_progress,
        cancel_check=cancel_check,
    )

    await assign_lecture_numbers(app.db, module_id)

    if cancel_check and cancel_check():
        log.info("pipeline_cancelled", module_id=module_id, stage="after_download")
        result.cancelled = True
        return result

    result.transcriptions = await transcribe_lectures(
        app,
        module_id,
        episode_ids=episode_ids,
        on_start=on_transcribe_start,
        on_complete=on_transcribe_complete,
        cancel_check=cancel_check,
    )

    if cancel_check and cancel_check():
        log.info("pipeline_cancelled", module_id=module_id, stage="after_transcribe")
        result.cancelled = True
        return result

    result.indexing = await index_lectures(
        app,
        module_id,
        episode_ids=episode_ids,
        on_start=on_index_start,
        on_complete=on_index_complete,
        cancel_check=cancel_check,
    )

    if cancel_check and cancel_check():
        log.info("pipeline_cancelled", module_id=module_id, stage="after_index")
        result.cancelled = True
        return result

    result.topics = await extract_topics_from_lectures(
        app, module_id, on_progress=on_topic_progress, force=True
    )

    if index_materials and course_id is not None:
        from sophia.services.material_index import index_materials as _index_materials

        result.material_chunks = await _index_materials(app, course_id)

    log.info(
        "pipeline_complete",
        module_id=module_id,
        downloads=len(result.downloads),
        transcriptions=len(result.transcriptions),
        indexed=len(result.indexing),
        topics=len(result.topics),
    )

    return result
