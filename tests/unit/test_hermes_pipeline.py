"""Tests for the Hermes pipeline orchestration service."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from sophia.domain.errors import TranscriptionError
from sophia.domain.models import (
    ComputeDevice,
    ComputeType,
    DownloadProgressEvent,
    HermesConfig,
    HermesWhisperConfig,
    Lecture,
    LectureTrack,
    TranscriptSegment,
)
from sophia.infra.engine import create_session_factory, session_scope
from sophia.infra.schema import lecture_downloads
from sophia.services.hermes_download import LectureDownloadResult
from sophia.services.hermes_index import IndexingResult
from sophia.services.hermes_transcribe import TranscriptionResult

from ..conftest import TEST_ORG_ID

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest.fixture(autouse=True)
def _whisper_config_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """The containers here are mocks with no config dir; the check has its own test."""
    monkeypatch.setattr("sophia.services.hermes_pipeline.check_whisper_config", MagicMock())


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
    source: str = "whisper",
) -> TranscriptionResult:
    return TranscriptionResult(
        episode_id=episode_id,
        title=title,
        srt_path=Path(f"/tmp/{episode_id}.srt") if status == "completed" else None,
        segment_count=segment_count,
        status=status,
        error=error,
        source=source,
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
async def test_pipeline_calls_stages_in_order(db: AsyncSession) -> None:
    """Captions come first so a captioned lecture is never downloaded, then the rest in order."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    call_order: list[str] = []

    async def _captions(*a: Any, **kw: Any) -> list[Any]:
        call_order.append("captions")
        return [_make_transcription("ep-captioned", "Captioned", source="captions")]

    async def _download(*a: Any, **kw: Any) -> list[Any]:
        call_order.append("download")
        return [_make_download()]

    async def _transcribe(*a: Any, **kw: Any) -> list[Any]:
        call_order.append("transcribe")
        return [_make_transcription()]

    async def _index(*a: Any, **kw: Any) -> list[Any]:
        call_order.append("index")
        return [_make_indexing()]

    async def _topics(*a: Any, **kw: Any) -> list[Any]:
        call_order.append("topics")
        return [_make_topic()]

    container = MagicMock()

    with (
        patch("sophia.services.hermes_pipeline.transcribe_from_captions", side_effect=_captions),
        patch("sophia.services.hermes_pipeline.download_lectures", side_effect=_download),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", side_effect=_transcribe),
        patch("sophia.services.hermes_pipeline.index_lectures", side_effect=_index),
        patch("sophia.services.hermes_pipeline.extract_topics_from_lectures", side_effect=_topics),
        patch("sophia.services.hermes_pipeline.assign_lecture_numbers", AsyncMock()),
    ):
        await run_pipeline(container, db, module_id=42)

    assert call_order == ["captions", "download", "transcribe", "index", "topics"]


@pytest.mark.asyncio
async def test_pipeline_refuses_unsupported_compute_type_before_any_stage(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A float16 config on a Pascal GPU fails at once, naming what the GPU supports."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline
    from sophia.services.hermes_setup import save_hermes_config
    from sophia.services.hermes_transcribe import check_whisper_config

    monkeypatch.setattr(
        "sophia.services.hermes_pipeline.check_whisper_config", check_whisper_config
    )
    save_hermes_config(
        HermesConfig(
            whisper=HermesWhisperConfig(device=ComputeDevice.CUDA, compute_type=ComputeType.FLOAT16)
        ),
        tmp_path,
    )
    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        SimpleNamespace(get_supported_compute_types=lambda _d: {"float32", "int8", "int8_float32"}),
    )
    container = MagicMock()
    container.settings.config_dir = tmp_path
    captions = AsyncMock(return_value=[])
    download = AsyncMock(return_value=[])

    with (
        patch("sophia.services.hermes_pipeline.transcribe_from_captions", captions),
        patch("sophia.services.hermes_pipeline.download_lectures", download),
        pytest.raises(TranscriptionError, match="float32, int8, int8_float32"),
    ):
        await run_pipeline(container, db, module_id=42)

    captions.assert_not_awaited()
    download.assert_not_awaited()


# ------------------------------------------------------------------
# Result aggregation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_aggregates_results(db: AsyncSession) -> None:
    """PipelineResult contains results from all four stages."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    captioned = [_make_transcription("ep-000", "Captioned", source="captions")]
    downloads = [_make_download("ep-001"), _make_download("ep-002")]
    transcriptions = [_make_transcription("ep-001"), _make_transcription("ep-002")]
    indexing = [_make_indexing("ep-001"), _make_indexing("ep-002")]
    topics = [_make_topic("Algebra"), _make_topic("Calculus")]

    container = MagicMock()

    with (
        patch(
            "sophia.services.hermes_pipeline.transcribe_from_captions",
            AsyncMock(return_value=captioned),
        ),
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
        patch("sophia.services.hermes_pipeline.assign_lecture_numbers", AsyncMock()),
    ):
        result = await run_pipeline(container, db, module_id=42)

    assert result.downloads == downloads
    assert result.transcriptions == captioned + transcriptions
    assert result.indexing == indexing
    assert result.topics == topics


# ------------------------------------------------------------------
# Passes module_id through
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_passes_module_id(db: AsyncSession) -> None:
    """Each stage receives the correct module_id."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    mock_download = AsyncMock(return_value=[])
    mock_transcribe = AsyncMock(return_value=[])
    mock_index = AsyncMock(return_value=[])
    mock_topics = AsyncMock(return_value=[])

    container = MagicMock()

    with (
        patch(
            "sophia.services.hermes_pipeline.transcribe_from_captions",
            AsyncMock(return_value=[]),
        ),
        patch("sophia.services.hermes_pipeline.download_lectures", mock_download),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", mock_transcribe),
        patch("sophia.services.hermes_pipeline.index_lectures", mock_index),
        patch("sophia.services.hermes_pipeline.extract_topics_from_lectures", mock_topics),
        patch("sophia.services.hermes_pipeline.assign_lecture_numbers", AsyncMock()),
    ):
        await run_pipeline(container, db, module_id=99)

    mock_download.assert_called_once()
    assert mock_download.call_args[0] == (container, db, 99)

    mock_transcribe.assert_called_once()
    assert mock_transcribe.call_args[0] == (container, db, 99)

    mock_index.assert_called_once()
    assert mock_index.call_args[0] == (container, db, 99)

    mock_topics.assert_called_once()
    assert mock_topics.call_args[0] == (container, db, 99)


# ------------------------------------------------------------------
# Cancellation
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_stops_on_cancel_before_first_stage(db: AsyncSession) -> None:
    """cancel_check returning True immediately → no stage is called."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    mock_captions = AsyncMock(return_value=[])
    mock_download = AsyncMock(return_value=[])

    container = MagicMock()

    with (
        patch("sophia.services.hermes_pipeline.transcribe_from_captions", mock_captions),
        patch("sophia.services.hermes_pipeline.download_lectures", mock_download),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", AsyncMock(return_value=[])),
        patch("sophia.services.hermes_pipeline.index_lectures", AsyncMock(return_value=[])),
        patch(
            "sophia.services.hermes_pipeline.extract_topics_from_lectures",
            AsyncMock(return_value=[]),
        ),
        patch("sophia.services.hermes_pipeline.assign_lecture_numbers", AsyncMock()),
    ):
        result = await run_pipeline(container, db, module_id=42, cancel_check=lambda: True)

    mock_download.assert_not_called()
    mock_captions.assert_not_called()
    assert result.cancelled is True


@pytest.mark.asyncio
async def test_pipeline_stops_between_stages(db: AsyncSession) -> None:
    """Cancel after download → transcribe not called."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    call_count = 0

    def _cancel_after_download() -> bool:
        return call_count >= 1

    async def _captions(*a: Any, **kw: Any) -> list[Any]:
        return []

    async def _download(*a: Any, **kw: Any) -> list[Any]:
        nonlocal call_count
        call_count += 1
        return [_make_download()]

    mock_transcribe = AsyncMock(return_value=[])

    container = MagicMock()

    with (
        patch("sophia.services.hermes_pipeline.transcribe_from_captions", side_effect=_captions),
        patch("sophia.services.hermes_pipeline.download_lectures", side_effect=_download),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", mock_transcribe),
        patch("sophia.services.hermes_pipeline.index_lectures", AsyncMock(return_value=[])),
        patch(
            "sophia.services.hermes_pipeline.extract_topics_from_lectures",
            AsyncMock(return_value=[]),
        ),
        patch("sophia.services.hermes_pipeline.assign_lecture_numbers", AsyncMock()),
    ):
        result = await run_pipeline(
            container, db, module_id=42, cancel_check=_cancel_after_download
        )

    assert result.downloads == [_make_download()]
    mock_transcribe.assert_not_called()
    assert result.cancelled is True


@pytest.mark.asyncio
async def test_pipeline_cancel_check_none_processes_all(db: AsyncSession) -> None:
    """Backward compatibility: cancel_check=None processes everything."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    call_order: list[str] = []

    async def _captions(*a: Any, **kw: Any) -> list[Any]:
        call_order.append("captions")
        return []

    async def _download(*a: Any, **kw: Any) -> list[Any]:
        call_order.append("download")
        return []

    async def _transcribe(*a: Any, **kw: Any) -> list[Any]:
        call_order.append("transcribe")
        return []

    async def _index(*a: Any, **kw: Any) -> list[Any]:
        call_order.append("index")
        return []

    async def _topics(*a: Any, **kw: Any) -> list[Any]:
        call_order.append("topics")
        return []

    container = MagicMock()

    with (
        patch("sophia.services.hermes_pipeline.transcribe_from_captions", side_effect=_captions),
        patch("sophia.services.hermes_pipeline.download_lectures", side_effect=_download),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", side_effect=_transcribe),
        patch("sophia.services.hermes_pipeline.index_lectures", side_effect=_index),
        patch("sophia.services.hermes_pipeline.extract_topics_from_lectures", side_effect=_topics),
        patch("sophia.services.hermes_pipeline.assign_lecture_numbers", AsyncMock()),
    ):
        result = await run_pipeline(container, db, module_id=42, cancel_check=None)

    assert call_order == ["captions", "download", "transcribe", "index", "topics"]
    assert result.cancelled is False


@pytest.mark.asyncio
async def test_pipeline_result_cancelled_flag(db: AsyncSession) -> None:
    """verify result.cancelled is True when cancelled."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    container = MagicMock()

    with (
        patch(
            "sophia.services.hermes_pipeline.transcribe_from_captions",
            AsyncMock(return_value=[]),
        ),
        patch("sophia.services.hermes_pipeline.download_lectures", AsyncMock(return_value=[])),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", AsyncMock(return_value=[])),
        patch("sophia.services.hermes_pipeline.index_lectures", AsyncMock(return_value=[])),
        patch(
            "sophia.services.hermes_pipeline.extract_topics_from_lectures",
            AsyncMock(return_value=[]),
        ),
        patch("sophia.services.hermes_pipeline.assign_lecture_numbers", AsyncMock()),
    ):
        result = await run_pipeline(container, db, module_id=42, cancel_check=lambda: True)

    assert result.cancelled is True
    assert result.downloads == []
    assert result.transcriptions == []
    assert result.indexing == []
    assert result.topics == []


@pytest.mark.asyncio
async def test_cancel_check_forwarded_to_stages(db: AsyncSession) -> None:
    """Verify cancel_check is passed through to each stage function."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    cancel_fn = MagicMock(return_value=False)
    mock_download = AsyncMock(return_value=[])
    mock_transcribe = AsyncMock(return_value=[])
    mock_index = AsyncMock(return_value=[])

    container = MagicMock()

    with (
        patch(
            "sophia.services.hermes_pipeline.transcribe_from_captions",
            AsyncMock(return_value=[]),
        ),
        patch("sophia.services.hermes_pipeline.download_lectures", mock_download),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", mock_transcribe),
        patch("sophia.services.hermes_pipeline.index_lectures", mock_index),
        patch(
            "sophia.services.hermes_pipeline.extract_topics_from_lectures",
            AsyncMock(return_value=[]),
        ),
        patch("sophia.services.hermes_pipeline.assign_lecture_numbers", AsyncMock()),
    ):
        await run_pipeline(container, db, module_id=42, cancel_check=cancel_fn)

    assert mock_download.call_args[1].get("cancel_check") is cancel_fn
    assert mock_transcribe.call_args[1].get("cancel_check") is cancel_fn
    assert mock_index.call_args[1].get("cancel_check") is cancel_fn


# ------------------------------------------------------------------
# Empty module — no episodes
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_empty_module(db: AsyncSession) -> None:
    """Pipeline handles modules with no episodes gracefully."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    container = MagicMock()

    with (
        patch(
            "sophia.services.hermes_pipeline.transcribe_from_captions",
            AsyncMock(return_value=[]),
        ),
        patch("sophia.services.hermes_pipeline.download_lectures", AsyncMock(return_value=[])),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", AsyncMock(return_value=[])),
        patch("sophia.services.hermes_pipeline.index_lectures", AsyncMock(return_value=[])),
        patch(
            "sophia.services.hermes_pipeline.extract_topics_from_lectures",
            AsyncMock(return_value=[]),
        ),
        patch("sophia.services.hermes_pipeline.assign_lecture_numbers", AsyncMock()),
    ):
        result = await run_pipeline(container, db, module_id=42)

    assert result.downloads == []
    assert result.transcriptions == []
    assert result.indexing == []
    assert result.topics == []


# ------------------------------------------------------------------
# Mixed results — some episodes fail, others succeed
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_mixed_episode_results(db: AsyncSession) -> None:
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
            "sophia.services.hermes_pipeline.transcribe_from_captions",
            AsyncMock(return_value=[]),
        ),
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
        patch("sophia.services.hermes_pipeline.assign_lecture_numbers", AsyncMock()),
    ):
        result = await run_pipeline(container, db, module_id=42)

    assert len(result.downloads) == 3
    assert result.downloads[1].status == "failed"
    assert len(result.transcriptions) == 2
    assert len(result.indexing) == 1
    assert len(result.topics) == 1


# ------------------------------------------------------------------
# Callbacks are forwarded
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_forwards_callbacks(db: AsyncSession) -> None:
    """Pipeline passes on_progress callbacks to each stage."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    mock_captions = AsyncMock(return_value=[])
    mock_download = AsyncMock(return_value=[])
    mock_transcribe = AsyncMock(return_value=[])
    mock_index = AsyncMock(return_value=[])
    mock_topics = AsyncMock(return_value=[])

    container = MagicMock()

    on_caption_start = MagicMock()
    on_caption_complete = MagicMock()
    on_download = MagicMock()
    on_transcribe_start = MagicMock()
    on_transcribe_complete = MagicMock()
    on_index_start = MagicMock()
    on_index_complete = MagicMock()
    on_topic_progress = MagicMock()

    with (
        patch("sophia.services.hermes_pipeline.transcribe_from_captions", mock_captions),
        patch("sophia.services.hermes_pipeline.download_lectures", mock_download),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", mock_transcribe),
        patch("sophia.services.hermes_pipeline.index_lectures", mock_index),
        patch("sophia.services.hermes_pipeline.extract_topics_from_lectures", mock_topics),
        patch("sophia.services.hermes_pipeline.assign_lecture_numbers", AsyncMock()),
    ):
        await run_pipeline(
            container,
            db,
            module_id=42,
            on_caption_start=on_caption_start,
            on_caption_complete=on_caption_complete,
            on_download_progress=on_download,
            on_transcribe_start=on_transcribe_start,
            on_transcribe_complete=on_transcribe_complete,
            on_index_start=on_index_start,
            on_index_complete=on_index_complete,
            on_topic_progress=on_topic_progress,
        )

    assert mock_captions.call_args.kwargs["on_start"] is on_caption_start
    assert mock_captions.call_args.kwargs["on_complete"] is on_caption_complete
    assert mock_download.call_args.kwargs["on_progress"] is on_download
    assert mock_transcribe.call_args.kwargs["on_start"] is on_transcribe_start
    assert mock_transcribe.call_args.kwargs["on_complete"] is on_transcribe_complete
    assert mock_index.call_args.kwargs["on_start"] is on_index_start
    assert mock_index.call_args.kwargs["on_complete"] is on_index_complete
    assert mock_topics.call_args.kwargs["on_progress"] is on_topic_progress


@pytest.mark.asyncio
async def test_pipeline_calls_assign_lecture_numbers(db: AsyncSession) -> None:
    """Pipeline calls assign_lecture_numbers after downloading."""
    from unittest.mock import patch

    from sophia.services.hermes_pipeline import run_pipeline

    container = MagicMock()

    with (
        patch(
            "sophia.services.hermes_pipeline.transcribe_from_captions",
            AsyncMock(return_value=[]),
        ),
        patch("sophia.services.hermes_pipeline.download_lectures", AsyncMock(return_value=[])),
        patch("sophia.services.hermes_pipeline.transcribe_lectures", AsyncMock(return_value=[])),
        patch("sophia.services.hermes_pipeline.index_lectures", AsyncMock(return_value=[])),
        patch(
            "sophia.services.hermes_pipeline.extract_topics_from_lectures",
            AsyncMock(return_value=[]),
        ),
        patch(
            "sophia.services.hermes_pipeline.assign_lecture_numbers",
            AsyncMock(),
        ) as mock_assign,
    ):
        await run_pipeline(container, db, module_id=42)

    mock_assign.assert_called_once_with(db, 42)


# ------------------------------------------------------------------
# Finished units outlive a later failure (#155)
#
# These drive the real download, numbering and Whisper stages against
# Postgres, each run in its own session_scope as `lectures process` opens
# it, and read the outcome back through another session.
# ------------------------------------------------------------------


def _recording(episode_id: str, title: str) -> Lecture:
    return Lecture(
        episode_id=episode_id,
        title=title,
        series_id="series-1",
        tracks=[
            LectureTrack(
                flavor="presenter/audio",
                url=f"https://example.com/{episode_id}.m4a",
                mimetype="audio/mp4",
            )
        ],
    )


async def _write_recording(_url: str, dest: Path) -> AsyncIterator[DownloadProgressEvent]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"audio")
    yield DownloadProgressEvent(bytes_downloaded=5, total_bytes=5, speed_bps=5.0)


def _opencast_app(tmp_path: Path, lectures: list[Lecture]) -> MagicMock:
    by_id = {lecture.episode_id: lecture for lecture in lectures}
    app = MagicMock()
    app.settings.data_dir = tmp_path
    app.opencast.get_series_episodes = AsyncMock(return_value=lectures)
    app.opencast.get_episode_detail = AsyncMock(side_effect=lambda _mid, eid: by_id.get(eid))  # type: ignore[arg-type]
    app.lecture_downloader.download_track = MagicMock(side_effect=_write_recording)
    return app


def _whisper(monkeypatch: pytest.MonkeyPatch, transcribe: MagicMock) -> None:
    transcriber = MagicMock()
    transcriber.transcribe = transcribe
    monkeypatch.setattr(
        "sophia.services.hermes_transcribe._create_transcriber", lambda _app: transcriber
    )


def _no_index_or_topics(monkeypatch: pytest.MonkeyPatch) -> None:
    for stage in ("index_lectures", "extract_topics_from_lectures"):
        monkeypatch.setattr(f"sophia.services.hermes_pipeline.{stage}", AsyncMock(return_value=[]))


async def _downloads(
    factory: async_sessionmaker[AsyncSession],
) -> dict[str, tuple[str, int | None]]:
    """Each download's status and lecture number, as another session reads them."""
    async with session_scope(factory, org_id=TEST_ORG_ID) as reader:
        rows = await reader.execute(
            select(
                lecture_downloads.c.episode_id,
                lecture_downloads.c.status,
                lecture_downloads.c.lecture_number,
            )
        )
        return {row.episode_id: (row.status, row.lecture_number) for row in rows}


async def _process(app: MagicMock, factory: async_sessionmaker[AsyncSession], **kw: Any) -> Any:
    from sophia.services.hermes_pipeline import run_pipeline

    async with session_scope(factory, org_id=TEST_ORG_ID) as session:
        return await run_pipeline(app, session, 42, **kw)


async def test_a_transcription_failure_keeps_every_download(
    tmp_path: Path, clean_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#154's float16 refusal, raised past the per-episode handler, no longer costs the downloads.

    The rerun downloads nothing again, and the lecture numbers the failed run
    assigned are the ones the finished run keeps.
    """
    factory = create_session_factory(clean_engine)
    app = _opencast_app(
        tmp_path,
        [
            _recording("ep-intro", "Einführung"),
            _recording("ep-vo1", "Vorlesung 1"),
            _recording("ep-review", "Wiederholung"),
        ],
    )
    _no_index_or_topics(monkeypatch)
    _whisper(
        monkeypatch,
        MagicMock(side_effect=ValueError("Requested float16 compute type, but the device …")),
    )

    with pytest.raises(ValueError, match="float16"):
        await _process(app, factory)

    after_failure = await _downloads(factory)
    assert after_failure == {
        "ep-vo1": ("completed", 1),
        "ep-intro": ("completed", 2),
        "ep-review": ("completed", 3),
    }

    _whisper(monkeypatch, MagicMock(return_value=[TranscriptSegment(start=0, end=1, text="x")]))
    result = await _process(app, factory)

    assert app.lecture_downloader.download_track.call_count == 3
    assert {download.status for download in result.downloads} == {"skipped"}
    assert {tr.status for tr in result.transcriptions} == {"completed"}
    assert await _downloads(factory) == after_failure


async def test_a_download_stage_cancelled_part_way_leaves_lecture_numbers_unset(
    tmp_path: Path, clean_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gap-filled over part of a module, a number would move once the rest arrived.

    Alone, "Einführung" is lecture 1; once "Vorlesung 1" is downloaded it is
    lecture 2. So the cut-short run leaves it unnumbered, and the full run
    numbers both exactly as one uninterrupted run would.
    """
    factory = create_session_factory(clean_engine)
    app = _opencast_app(
        tmp_path, [_recording("ep-intro", "Einführung"), _recording("ep-vo1", "Vorlesung 1")]
    )
    monkeypatch.setattr(
        "sophia.services.hermes_pipeline.transcribe_lectures", AsyncMock(return_value=[])
    )
    _no_index_or_topics(monkeypatch)

    partial = await _process(
        app,
        factory,
        cancel_check=lambda: app.lecture_downloader.download_track.call_count >= 1,
    )

    assert partial.cancelled is True
    assert await _downloads(factory) == {"ep-intro": ("completed", None)}

    await _process(app, factory)

    assert await _downloads(factory) == {
        "ep-intro": ("completed", 2),
        "ep-vo1": ("completed", 1),
    }
