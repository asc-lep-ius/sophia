"""Tests for the Hermes indexing and search orchestration service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from sophia.domain.models import (
    HermesConfig,
    KnowledgeChunk,
    TranscriptSegment,
)
from sophia.infra.engine import create_session_factory, session_scope

from .._sql import exec_sql
from ..conftest import TEST_ORG_ID

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession


def _run_sync(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Stand-in for asyncio.to_thread that runs the function synchronously."""
    return fn(*args, **kwargs)


@pytest.fixture
def app(db: AsyncSession, tmp_path: Path) -> MagicMock:
    mock = MagicMock()
    mock.db = db
    mock.settings.config_dir = tmp_path
    mock.settings.cache_dir = tmp_path / "cache"
    mock.settings.data_dir = tmp_path / "data"
    return mock


async def _insert_download(
    db: AsyncSession,
    *,
    episode_id: str = "ep-001",
    module_id: int = 42,
    title: str = "Lecture 1",
) -> None:
    await exec_sql(
        db,
        """INSERT INTO lecture_downloads
           (episode_id, module_id, series_id, title, track_url, track_mimetype,
            file_path, status)
           VALUES (?, ?, 'series-1', ?, 'https://example.com/a.mp3', 'audio/mpeg',
                   '/tmp/audio.mp3', 'completed')""",
        (episode_id, module_id, title),
    )


async def _insert_transcription(
    db: AsyncSession,
    *,
    episode_id: str = "ep-001",
    module_id: int = 42,
) -> None:
    await exec_sql(
        db,
        "INSERT INTO transcriptions (episode_id, module_id, segment_count, status) "
        "VALUES (?, ?, 5, 'completed')",
        (episode_id, module_id),
    )


async def _insert_caption_transcription(
    db: AsyncSession,
    *,
    episode_id: str = "ep-001",
    module_id: int = 42,
    title: str = "Captioned lecture",
) -> None:
    """A transcript read from the player's captions: no download row behind it."""
    await exec_sql(
        db,
        "INSERT INTO transcriptions (episode_id, module_id, segment_count, status, source, title) "
        "VALUES (?, ?, 5, 'completed', 'captions', ?)",
        (episode_id, module_id, title),
    )


async def _insert_segments(
    db: AsyncSession,
    *,
    episode_id: str = "ep-001",
    count: int = 5,
) -> None:
    for i in range(count):
        await exec_sql(
            db,
            "INSERT INTO transcript_segments "
            "(episode_id, segment_index, start_time, end_time, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (episode_id, i, float(i * 5), float((i + 1) * 5), f"Segment {i}"),
        )


# ---------------------------------------------------------------------------
# chunk_segments — pure function tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunk_segments() -> None:
    from sophia.services.hermes_index import chunk_segments

    segments = [
        TranscriptSegment(start=float(i * 5), end=float((i + 1) * 5), text=f"Seg {i}")
        for i in range(7)
    ]

    chunks = chunk_segments(segments, "ep-001")

    # With 7 segments, chunk_size=3, overlap=1: windows start at 0,2,4 → 3 chunks
    assert len(chunks) == 3

    # First chunk: segments 0,1,2
    assert chunks[0].chunk_id == "ep-001_0"
    assert chunks[0].chunk_index == 0
    assert chunks[0].text == "Seg 0 Seg 1 Seg 2"
    assert chunks[0].start_time == 0.0
    assert chunks[0].end_time == 15.0

    # Second chunk: segments 2,3,4 (overlap=1 from previous)
    assert chunks[1].chunk_id == "ep-001_1"
    assert chunks[1].chunk_index == 1
    assert chunks[1].text == "Seg 2 Seg 3 Seg 4"
    assert chunks[1].start_time == 10.0
    assert chunks[1].end_time == 25.0

    # Third chunk: segments 4,5,6
    assert chunks[2].chunk_id == "ep-001_2"
    assert chunks[2].chunk_index == 2
    assert chunks[2].text == "Seg 4 Seg 5 Seg 6"
    assert chunks[2].start_time == 20.0
    assert chunks[2].end_time == 35.0


@pytest.mark.asyncio
async def test_chunk_segments_fewer_than_chunk_size() -> None:
    from sophia.services.hermes_index import chunk_segments

    segments = [
        TranscriptSegment(start=0.0, end=5.0, text="First"),
        TranscriptSegment(start=5.0, end=10.0, text="Second"),
    ]

    chunks = chunk_segments(segments, "ep-002")

    assert len(chunks) == 1
    assert chunks[0].chunk_id == "ep-002_0"
    assert chunks[0].text == "First Second"
    assert chunks[0].start_time == 0.0
    assert chunks[0].end_time == 10.0


# ---------------------------------------------------------------------------
# index_lectures — orchestration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_lectures_happy_path(app: MagicMock, db: AsyncSession) -> None:
    from sophia.services.hermes_index import index_lectures

    await _insert_download(db)
    await _insert_transcription(db)
    await _insert_segments(db, count=5)

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1] * 10 for _ in range(3)]

    mock_store = MagicMock()

    on_start = MagicMock()
    on_complete = MagicMock()

    with (
        patch(
            "sophia.services.hermes_index.load_hermes_config",
            return_value=HermesConfig(),
        ),
        patch(
            "sophia.services.hermes_index.SentenceTransformerEmbedder",
            return_value=mock_embedder,
        ),
        patch(
            "sophia.services.hermes_index.ChromaKnowledgeStore",
            return_value=mock_store,
        ),
        patch(
            "sophia.services.hermes_index.asyncio.to_thread",
            side_effect=_run_sync,
        ),
    ):
        results = await index_lectures(app, db, 42, on_start=on_start, on_complete=on_complete)

    assert len(results) == 1
    r = results[0]
    assert r.episode_id == "ep-001"
    assert r.status == "completed"
    assert r.chunk_count > 0

    on_start.assert_called_once_with("ep-001", "Lecture 1")
    on_complete.assert_called_once_with("ep-001", r.chunk_count)

    # Verify knowledge_index row in DB
    cursor = await exec_sql(
        db, "SELECT status, chunk_count FROM knowledge_index WHERE episode_id = 'ep-001'"
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "completed"
    assert row[1] > 0

    # Verify embedder was called with chunk texts
    mock_embedder.embed.assert_called_once()
    # Verify store received chunks and embeddings
    mock_store.add_chunks.assert_called_once()


@pytest.mark.asyncio
async def test_index_lectures_reads_a_caption_transcript_without_a_download(
    app: MagicMock, db: AsyncSession
) -> None:
    """A caption transcript is indexed like a Whisper one and keeps its own title."""
    from sophia.services.hermes_index import index_lectures

    await _insert_caption_transcription(db, title="Vorlesung - VU vom 2026-01-16")
    await _insert_segments(db, count=5)

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [[0.1] * 10 for _ in range(3)]
    on_start = MagicMock()

    with (
        patch("sophia.services.hermes_index.load_hermes_config", return_value=HermesConfig()),
        patch(
            "sophia.services.hermes_index.SentenceTransformerEmbedder", return_value=mock_embedder
        ),
        patch("sophia.services.hermes_index.ChromaKnowledgeStore", return_value=MagicMock()),
        patch("sophia.services.hermes_index.asyncio.to_thread", side_effect=_run_sync),
    ):
        results = await index_lectures(app, db, 42, on_start=on_start)

    assert [(r.episode_id, r.status) for r in results] == [("ep-001", "completed")]
    assert results[0].chunk_count > 0
    on_start.assert_called_once_with("ep-001", "Vorlesung - VU vom 2026-01-16")


@pytest.mark.asyncio
async def test_index_lectures_skips_completed(app: MagicMock, db: AsyncSession) -> None:
    from sophia.services.hermes_index import index_lectures

    await _insert_download(db)
    await _insert_transcription(db)
    await _insert_segments(db, count=5)

    # Pre-insert completed knowledge_index row
    await exec_sql(
        db,
        "INSERT INTO knowledge_index (episode_id, module_id, chunk_count, status, indexed_at) "
        "VALUES ('ep-001', 42, 3, 'completed', datetime('now'))",
    )

    results = await index_lectures(app, db, 42)

    assert len(results) == 1
    assert results[0].status == "skipped"


@pytest.mark.asyncio
async def test_index_lectures_no_transcriptions(app: MagicMock, db: AsyncSession) -> None:
    from sophia.services.hermes_index import index_lectures

    results = await index_lectures(app, db, 42)

    assert results == []


# ---------------------------------------------------------------------------
# search_lectures — search tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_lectures(app: MagicMock, db: AsyncSession) -> None:
    from sophia.services.hermes_index import search_lectures

    await _insert_download(db, title="Intro to Algorithms")

    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.2] * 10

    search_chunk = KnowledgeChunk(
        chunk_id="ep-001_0",
        episode_id="ep-001",
        chunk_index=0,
        text="Algorithms are step-by-step procedures",
        start_time=0.0,
        end_time=15.0,
    )
    mock_store = MagicMock()
    mock_store.search.return_value = [(search_chunk, 0.92)]

    with (
        patch(
            "sophia.services.hermes_index.load_hermes_config",
            return_value=HermesConfig(),
        ),
        patch("sophia.services.hermes_index.query_embedder", return_value=mock_embedder),
        patch("sophia.services.hermes_index.knowledge_store", return_value=mock_store),
        patch(
            "sophia.services.hermes_index.asyncio.to_thread",
            side_effect=_run_sync,
        ),
    ):
        results = await search_lectures(app, db, 42, "What are algorithms?")

    assert len(results) == 1
    r = results[0]
    assert r.episode_id == "ep-001"
    assert r.title == "Intro to Algorithms"
    assert r.chunk_text == "Algorithms are step-by-step procedures"
    assert r.start_time == 0.0
    assert r.end_time == 15.0
    assert r.score == pytest.approx(0.92)  # pyright: ignore[reportUnknownMemberType]

    # Verify search was scoped to module episodes
    mock_store.search.assert_called_once()
    call_kwargs = mock_store.search.call_args[1]
    assert "episode_ids" in call_kwargs
    assert call_kwargs["episode_ids"] == ["ep-001"]


@pytest.mark.asyncio
async def test_search_lectures_scopes_to_caption_transcripts_too(
    app: MagicMock, db: AsyncSession
) -> None:
    """A module's search scope is its episodes, downloaded or captioned."""
    from sophia.services.hermes_index import search_lectures

    await _insert_download(db, episode_id="ep-dl", title="Downloaded")
    await _insert_caption_transcription(db, episode_id="ep-cc", title="Captioned")

    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.2] * 10
    chunk = KnowledgeChunk(
        chunk_id="ep-cc_0",
        episode_id="ep-cc",
        chunk_index=0,
        text="Generische Datenstrukturen",
        start_time=2.91,
        end_time=6.4,
    )
    mock_store = MagicMock()
    mock_store.search.return_value = [(chunk, 0.9)]

    with (
        patch("sophia.services.hermes_index.load_hermes_config", return_value=HermesConfig()),
        patch("sophia.services.hermes_index.query_embedder", return_value=mock_embedder),
        patch("sophia.services.hermes_index.knowledge_store", return_value=mock_store),
        patch("sophia.services.hermes_index.asyncio.to_thread", side_effect=_run_sync),
    ):
        results = await search_lectures(app, db, 42, "Datenstrukturen")

    assert sorted(mock_store.search.call_args[1]["episode_ids"]) == ["ep-cc", "ep-dl"]
    assert [(r.episode_id, r.title) for r in results] == [("ep-cc", "Captioned")]


@pytest.mark.asyncio
async def test_search_lectures_pdf_filter_includes_material_ids(
    app: MagicMock, db: AsyncSession
) -> None:
    """With source_filter='pdf' and course_id, search includes material episode IDs."""
    from sophia.services.hermes_index import search_lectures

    await _insert_download(db, episode_id="ep-001", module_id=42, title="Lecture 1")
    # Insert course material with distinct course_id=999
    await exec_sql(
        db,
        "INSERT INTO course_materials (id, course_id, module_id, name, url, status) "
        "VALUES (?, ?, ?, ?, ?, 'completed')",
        (10, 999, 42, "Slides.pdf", "https://example.com/s.pdf"),
    )

    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1, 0.2]
    mock_store = MagicMock()
    mock_store.search.return_value = []

    with (
        patch("sophia.services.hermes_index.load_hermes_config", return_value=HermesConfig()),
        patch("sophia.services.hermes_index.query_embedder", return_value=mock_embedder),
        patch("sophia.services.hermes_index.knowledge_store", return_value=mock_store),
        patch("sophia.services.hermes_index.asyncio.to_thread", side_effect=_run_sync),
    ):
        await search_lectures(app, db, 42, "test query", source_filter="pdf", course_id=999)

    call_kwargs = mock_store.search.call_args[1]
    episode_ids = call_kwargs["episode_ids"]
    # Must include both lecture and material episode IDs
    assert "ep-001" in episode_ids
    assert "mat-10" in episode_ids


async def test_an_episode_indexed_before_a_failure_stays_indexed(
    tmp_path: Path, clean_engine: AsyncEngine
) -> None:
    """Each episode's row is committed once its chunks are stored (#155)."""
    from sophia.services.hermes_index import index_lectures

    factory = create_session_factory(clean_engine)
    async with session_scope(factory, org_id=TEST_ORG_ID) as setup:
        for episode_id in ("ep-001", "ep-002"):
            await _insert_transcription(setup, episode_id=episode_id)
            await _insert_segments(setup, episode_id=episode_id, count=3)

    embedder = MagicMock()
    embedder.embed.side_effect = [[[0.1] * 4], RuntimeError("CUDA error: no kernel image")]
    app = MagicMock()
    app.settings.data_dir = tmp_path

    with (
        patch("sophia.services.hermes_index._create_embedder", return_value=embedder),
        patch("sophia.services.hermes_index._create_store", return_value=MagicMock()),
        pytest.raises(RuntimeError, match="no kernel image"),
    ):
        async with session_scope(factory, org_id=TEST_ORG_ID) as session:
            await index_lectures(app, session, 42)

    async with session_scope(factory, org_id=TEST_ORG_ID) as reader:
        rows = (await exec_sql(reader, "SELECT episode_id, status FROM knowledge_index")).all()
    assert len(rows) == 1
    assert rows[0].status == "completed"
