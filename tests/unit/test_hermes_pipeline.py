"""Tests for the Hermes pipeline orchestration service."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from sophia.services.hermes_download import LectureDownloadResult
from sophia.services.hermes_index import IndexingResult
from sophia.services.hermes_transcribe import TranscriptionResult


def _make_download(
    episode_id: str = "ep-001",
    title: str = "Lecture 1",
    status: str = "completed",
    *,
    file_path: Path | None = None,
    error: str | None = None,
) -> LectureDownloadResult:
    return LectureDownloadResult(
        episode_id=episode_id,
        title=title,
        file_path=file_path or Path(f"/tmp/{episode_id}.m4a"),
        status=status,
        error=error,
    )


def _make_transcription(
    episode_id: str = "ep-001",
    title: str = "Lecture 1",
    status: str = "completed",
    segment_count: int = 42,
    *,
    error: str | None = None,
) -> TranscriptionResult:
    return TranscriptionResult(
        episode_id=episode_id,
        title=title,
        srt_path=Path(f"/tmp/{episode_id}.srt") if status == "completed" else None,
        segment_count=segment_count,
        status=status,
        error=error,
    )


def _make_indexing(
    episode_id: str = "ep-001",
    title: str = "Lecture 1",
    status: str = "completed",
    chunk_count: int = 10,
    *,
    error: str | None = None,
) -> IndexingResult:
    return IndexingResult(
        episode_id=episode_id,
        title=title,
        chunk_count=chunk_count,
        status=status,
        error=error,
    )


def _make_topic(topic: str = "Linear Algebra", course_id: int = 42):
    from sophia.domain.models import TopicMapping

    return TopicMapping(topic=topic, course_id=course_id)


# ------------------------------------------------------------------
# Stage call order
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_calls_stages_in_order() -> None:
    """All four stages are called sequentially: download → transcribe → index → topics."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    call_order: list[str] = []

    async def _download(*a, **kw):
        call_order.append("download")
        return [_make_download()]

    async def _transcribe(*a, **kw):
        call_order.append("transcribe")
        return [_make_transcription()]

    async def _index(*a, **kw):
        call_order.append("index")
        return [_make_indexing()]

    async def _topics(*a, **kw):
        call_order.append("topics")
        return [_make_topic()]

    container = MagicMock()

    with (
        patch("sophia.services.hermes_pipeline.download_lectures", side_effect=_download),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", side_effect=_transcribe),
        patch("sophia.services.hermes_pipeline.index_lectures", side_effect=_index),
        patch("sophia.services.hermes_pipeline.extract_topics_from_lectures", side_effect=_topics),
    ):
        await run_pipeline(container, module_id=42)

    assert call_order == ["download", "transcribe", "index", "topics"]


# ------------------------------------------------------------------
# Result aggregation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_aggregates_results() -> None:
    """PipelineResult contains results from all four stages."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    downloads = [_make_download("ep-001"), _make_download("ep-002")]
    transcriptions = [_make_transcription("ep-001"), _make_transcription("ep-002")]
    indexing = [_make_indexing("ep-001"), _make_indexing("ep-002")]
    topics = [_make_topic("Algebra"), _make_topic("Calculus")]

    container = MagicMock()

    with (
        patch(
            "sophia.services.hermes_pipeline.download_lectures",
            AsyncMock(return_value=downloads),
        ),
        patch(
            "sophia.services.hermes_pipeline.transcribe_lectures",
            AsyncMock(return_value=transcriptions),
        ),
        patch(
            "sophia.services.hermes_pipeline.index_lectures",
            AsyncMock(return_value=indexing),
        ),
        patch(
            "sophia.services.hermes_pipeline.extract_topics_from_lectures",
            AsyncMock(return_value=topics),
        ),
    ):
        result = await run_pipeline(container, module_id=42)

    assert result.downloads == downloads
    assert result.transcriptions == transcriptions
    assert result.indexing == indexing
    assert result.topics == topics


# ------------------------------------------------------------------
# Passes module_id through
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_passes_module_id() -> None:
    """Each stage receives the correct module_id."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    mock_download = AsyncMock(return_value=[])
    mock_transcribe = AsyncMock(return_value=[])
    mock_index = AsyncMock(return_value=[])
    mock_topics = AsyncMock(return_value=[])

    container = MagicMock()

    with (
        patch("sophia.services.hermes_pipeline.download_lectures", mock_download),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", mock_transcribe),
        patch("sophia.services.hermes_pipeline.index_lectures", mock_index),
        patch("sophia.services.hermes_pipeline.extract_topics_from_lectures", mock_topics),
    ):
        await run_pipeline(container, module_id=99)

    mock_download.assert_called_once()
    assert mock_download.call_args[0] == (container, 99)

    mock_transcribe.assert_called_once()
    assert mock_transcribe.call_args[0] == (container, 99)

    mock_index.assert_called_once()
    assert mock_index.call_args[0] == (container, 99)

    mock_topics.assert_called_once()
    assert mock_topics.call_args[0] == (container, 99)


# ------------------------------------------------------------------
# Empty module — no episodes
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_empty_module() -> None:
    """Pipeline handles modules with no episodes gracefully."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    container = MagicMock()

    with (
        patch("sophia.services.hermes_pipeline.download_lectures", AsyncMock(return_value=[])),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", AsyncMock(return_value=[])),
        patch("sophia.services.hermes_pipeline.index_lectures", AsyncMock(return_value=[])),
        patch(
            "sophia.services.hermes_pipeline.extract_topics_from_lectures",
            AsyncMock(return_value=[]),
        ),
    ):
        result = await run_pipeline(container, module_id=42)

    assert result.downloads == []
    assert result.transcriptions == []
    assert result.indexing == []
    assert result.topics == []


# ------------------------------------------------------------------
# Mixed results — some episodes fail, others succeed
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_mixed_episode_results() -> None:
    """A failure in one episode doesn't stop other episodes from being processed."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    downloads = [
        _make_download("ep-001", status="completed"),
        _make_download("ep-002", status="failed", error="Network timeout"),
        _make_download("ep-003", status="skipped"),
    ]
    transcriptions = [
        _make_transcription("ep-001", status="completed"),
        _make_transcription("ep-002", status="skipped"),
    ]
    indexing = [_make_indexing("ep-001", status="completed")]
    topics = [_make_topic("Topic A")]

    container = MagicMock()

    with (
        patch(
            "sophia.services.hermes_pipeline.download_lectures",
            AsyncMock(return_value=downloads),
        ),
        patch(
            "sophia.services.hermes_pipeline.transcribe_lectures",
            AsyncMock(return_value=transcriptions),
        ),
        patch(
            "sophia.services.hermes_pipeline.index_lectures",
            AsyncMock(return_value=indexing),
        ),
        patch(
            "sophia.services.hermes_pipeline.extract_topics_from_lectures",
            AsyncMock(return_value=topics),
        ),
    ):
        result = await run_pipeline(container, module_id=42)

    assert len(result.downloads) == 3
    assert result.downloads[1].status == "failed"
    assert len(result.transcriptions) == 2
    assert len(result.indexing) == 1
    assert len(result.topics) == 1


# ------------------------------------------------------------------
# Callbacks are forwarded
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_forwards_callbacks() -> None:
    """Pipeline passes on_progress callbacks to each stage."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    mock_download = AsyncMock(return_value=[])
    mock_transcribe = AsyncMock(return_value=[])
    mock_index = AsyncMock(return_value=[])
    mock_topics = AsyncMock(return_value=[])

    container = MagicMock()

    on_download = MagicMock()
    on_transcribe_start = MagicMock()
    on_transcribe_complete = MagicMock()
    on_index_start = MagicMock()
    on_index_complete = MagicMock()
    on_topic_progress = MagicMock()

    with (
        patch("sophia.services.hermes_pipeline.download_lectures", mock_download),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", mock_transcribe),
        patch("sophia.services.hermes_pipeline.index_lectures", mock_index),
        patch("sophia.services.hermes_pipeline.extract_topics_from_lectures", mock_topics),
    ):
        await run_pipeline(
            container,
            module_id=42,
            on_download_progress=on_download,
            on_transcribe_start=on_transcribe_start,
            on_transcribe_complete=on_transcribe_complete,
            on_index_start=on_index_start,
            on_index_complete=on_index_complete,
            on_topic_progress=on_topic_progress,
        )

    assert mock_download.call_args.kwargs["on_progress"] is on_download
    assert mock_transcribe.call_args.kwargs["on_start"] is on_transcribe_start
    assert mock_transcribe.call_args.kwargs["on_complete"] is on_transcribe_complete
    assert mock_index.call_args.kwargs["on_start"] is on_index_start
    assert mock_index.call_args.kwargs["on_complete"] is on_index_complete
    assert mock_topics.call_args.kwargs["on_progress"] is on_topic_progress
