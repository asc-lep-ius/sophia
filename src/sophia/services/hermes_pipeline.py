"""Hermes pipeline orchestration — captions → download → transcribe → index → topics.

The stages come in two groups, because on a Pascal GPU they cannot share a
process: Whisper runs on the GPU as int8, while PyTorch has no kernels for it,
so embedding has to run with the GPU hidden. :func:`run_media_stages` is the
first group and :func:`run_knowledge_stages` the second; the worker runs each
in its own process, and :func:`run_pipeline` runs both in one for the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from sophia.domain.errors import EmbeddingError, TopicExtractionError
from sophia.infra.engine import commit_unit
from sophia.services.athena_study import extract_topics_from_lectures
from sophia.services.athena_topics import LectureTopicResult, extract_topics_per_lecture
from sophia.services.hermes_catalog import lecture_module_course
from sophia.services.hermes_download import LectureDownloadResult, download_lectures
from sophia.services.hermes_index import IndexingResult, index_lectures
from sophia.services.hermes_manage import assign_lecture_numbers
from sophia.services.hermes_transcribe import (
    TranscriptionResult,
    check_whisper_config,
    transcribe_from_captions,
    transcribe_lectures,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

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
    lecture_topics: list[LectureTopicResult] = field(default_factory=lambda: [])
    material_chunks: int = 0
    cancelled: bool = False


async def run_media_stages(
    app: AppContainer,
    session: AsyncSession,
    module_id: int,
    *,
    cancel_check: Callable[[], bool] | None = None,
    on_caption_start: Callable[[str, str], None] | None = None,
    on_caption_complete: Callable[[str, int], None] | None = None,
    on_download_progress: Callable[[str, DownloadProgressEvent], None] | None = None,
    on_transcribe_start: Callable[[str, str], None] | None = None,
    on_transcribe_complete: Callable[[str, int], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
) -> PipelineResult:
    """Captions, download, lecture numbers and Whisper — everything that needs the GPU.

    The player's captions come first so that a lecture that has them is never
    downloaded or sent through Whisper; the download stage skips every episode
    that already has a transcript. Each stage handles per-episode failures
    internally and commits every finished episode, so a failure or an
    interrupt costs only the unit in flight.
    """
    result = PipelineResult()
    log.info("pipeline_start", module_id=module_id)
    check_whisper_config(app)

    if cancel_check and cancel_check():
        return _cancelled(result, module_id, "before_captions")

    _stage(on_stage, "captions")
    result.transcriptions = await transcribe_from_captions(
        app,
        session,
        module_id,
        on_start=on_caption_start,
        on_complete=on_caption_complete,
        cancel_check=cancel_check,
    )
    if cancel_check and cancel_check():
        return _cancelled(result, module_id, "after_captions")

    _stage(on_stage, "download")
    result.downloads = await download_lectures(
        app,
        session,
        module_id,
        on_progress=on_download_progress,
        cancel_check=cancel_check,
    )
    if cancel_check and cancel_check():
        # Numbers gap-filled over part of a module would move once the rest
        # arrives, so a download stage that stopped short leaves them unset.
        return _cancelled(result, module_id, "after_download")

    await assign_lecture_numbers(session, module_id)
    await commit_unit(session)

    _stage(on_stage, "transcribe")
    whisper_results = await transcribe_lectures(
        app,
        session,
        module_id,
        on_start=on_transcribe_start,
        on_complete=on_transcribe_complete,
        cancel_check=cancel_check,
    )
    result.transcriptions = [*result.transcriptions, *whisper_results]
    if cancel_check and cancel_check():
        return _cancelled(result, module_id, "after_transcribe")
    return result


async def run_knowledge_stages(
    app: AppContainer,
    session: AsyncSession,
    module_id: int,
    *,
    course_id: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_index_start: Callable[[str, str], None] | None = None,
    on_index_complete: Callable[[str, int], None] | None = None,
    on_topic_progress: Callable[[str], None] | None = None,
    on_stage: Callable[[str], None] | None = None,
    strict: bool = False,
) -> PipelineResult:
    """Index the module's transcripts and extract each lecture's topics.

    Topics belong to the course that owns the module, ``course_id`` when the
    caller knows it and the one discovery recorded otherwise. A module with no
    known owner gets no topics: filed under the module id, the browser could
    never read them (#127). Each lecture is read on its own and remembered,
    so a second run reads only what is new and keeps the topics a student has
    rated (#128).

    With ``strict``, a stage in which every episode it attempted failed raises
    rather than returning: that is the whole GPU or the model being unusable,
    not one bad lecture, and the worker must report it as a failure.
    """
    result = PipelineResult()

    _stage(on_stage, "index")
    result.indexing = await index_lectures(
        app,
        session,
        module_id,
        on_start=on_index_start,
        on_complete=on_index_complete,
        cancel_check=cancel_check,
    )
    if strict:
        _raise_if_all_failed(
            [(item.status, item.error) for item in result.indexing], EmbeddingError, "indexing"
        )
    if cancel_check and cancel_check():
        return _cancelled(result, module_id, "after_index")

    owner_id = (
        course_id if course_id is not None else await lecture_module_course(session, module_id)
    )
    if owner_id is None:
        log.warning("pipeline_topics_skipped_no_owner", module_id=module_id)
        return result

    _stage(on_stage, "topics")
    result.lecture_topics = await extract_topics_per_lecture(
        app,
        session,
        owner_id,
        module_id=module_id,
        on_progress=on_topic_progress,
        cancel_check=cancel_check,
    )
    if strict:
        _raise_if_all_failed(
            [(item.status, item.error) for item in result.lecture_topics],
            TopicExtractionError,
            "topic extraction",
        )
    result.topics = await extract_topics_from_lectures(
        app, session, owner_id, on_progress=on_topic_progress
    )
    await commit_unit(session)
    return result


async def run_pipeline(
    app: AppContainer,
    session: AsyncSession,
    module_id: int,
    *,
    index_materials: bool = False,
    course_id: int | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_caption_start: Callable[[str, str], None] | None = None,
    on_caption_complete: Callable[[str, int], None] | None = None,
    on_download_progress: Callable[[str, DownloadProgressEvent], None] | None = None,
    on_transcribe_start: Callable[[str, str], None] | None = None,
    on_transcribe_complete: Callable[[str, int], None] | None = None,
    on_index_start: Callable[[str, str], None] | None = None,
    on_index_complete: Callable[[str, int], None] | None = None,
    on_topic_progress: Callable[[str], None] | None = None,
) -> PipelineResult:
    """Orchestrate the full lecture pipeline for a module, in one process."""
    result = await run_media_stages(
        app,
        session,
        module_id,
        cancel_check=cancel_check,
        on_caption_start=on_caption_start,
        on_caption_complete=on_caption_complete,
        on_download_progress=on_download_progress,
        on_transcribe_start=on_transcribe_start,
        on_transcribe_complete=on_transcribe_complete,
    )
    if result.cancelled:
        return result

    knowledge = await run_knowledge_stages(
        app,
        session,
        module_id,
        course_id=course_id,
        cancel_check=cancel_check,
        on_index_start=on_index_start,
        on_index_complete=on_index_complete,
        on_topic_progress=on_topic_progress,
    )
    result.indexing = knowledge.indexing
    result.topics = knowledge.topics
    result.lecture_topics = knowledge.lecture_topics
    result.cancelled = knowledge.cancelled
    if result.cancelled:
        return result

    if index_materials and course_id is not None:
        from sophia.services.material_index import index_materials as _index_materials

        result.material_chunks = await _index_materials(app, session, course_id)

    log.info(
        "pipeline_complete",
        module_id=module_id,
        downloads=len(result.downloads),
        transcriptions=len(result.transcriptions),
        indexed=len(result.indexing),
        topics=len(result.topics),
    )
    return result


def _stage(on_stage: Callable[[str], None] | None, name: str) -> None:
    if on_stage:
        on_stage(name)


def _cancelled(result: PipelineResult, module_id: int, stage: str) -> PipelineResult:
    log.info("pipeline_cancelled", module_id=module_id, stage=stage)
    result.cancelled = True
    return result


def _raise_if_all_failed(
    outcomes: list[tuple[str, str | None]],
    error_type: type[Exception],
    stage: str,
) -> None:
    attempted = [(status, error) for status, error in outcomes if status != "skipped"]
    if not attempted or any(status != "failed" for status, _ in attempted):
        return
    first_error = next((error for _, error in attempted if error), "no reason recorded")
    raise error_type(f"{stage} failed for every lecture — first error: {first_error}")
