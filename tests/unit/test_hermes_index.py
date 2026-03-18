"""Tests for the Hermes indexing and search orchestration service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import aiosqlite
import pytest

from sophia.domain.models import (
    HermesConfig,
    KnowledgeChunk,
    TranscriptSegment,
)
from sophia.infra.persistence import run_migrations

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


def _run_sync(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Stand-in for asyncio.to_thread that runs the function synchronously."""
    return fn(*args, **kwargs)


@pytest.fixture
async def db():
    db_conn = await aiosqlite.connect(":memory:")
    await db_conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(db_conn)
    yield db_conn
    await db_conn.close()


@pytest.fixture
def app(db: aiosqlite.Connection, tmp_path: Path) -> MagicMock:
    mock = MagicMock()
    mock.db = db
    mock.settings.config_dir = tmp_path
    mock.settings.cache_dir = tmp_path / "cache"
    mock.settings.data_dir = tmp_path / "data"
    return mock


async def _insert_download(
    db: aiosqlite.Connection,
    *,
    episode_id: str = "ep-001",
    module_id: int = 42,
    title: str = "Lecture 1",
) -> None:
    await db.execute(
        """INSERT INTO lecture_downloads
           (episode_id, module_id, series_id, title, track_url, track_mimetype,
            file_path, status)
           VALUES (?, ?, 'series-1', ?, 'https://example.com/a.mp3', 'audio/mpeg',
                   '/tmp/audio.mp3', 'completed')""",
        (episode_id, module_id, title),
    )
    await db.commit()


async def _insert_transcription(
    db: aiosqlite.Connection,
    *,
    episode_id: str = "ep-001",
    module_id: int = 42,
) -> None:
    await db.execute(
        "INSERT INTO transcriptions (episode_id, module_id, segment_count, status) "
        "VALUES (?, ?, 5, 'completed')",
        (episode_id, module_id),
    )
    await db.commit()


async def _insert_segments(
    db: aiosqlite.Connection,
    *,
    episode_id: str = "ep-001",
    count: int = 5,
) -> None:
    for i in range(count):
        await db.execute(
            "INSERT INTO transcript_segments "
            "(episode_id, segment_index, start_time, end_time, text) "
            "VALUES (?, ?, ?, ?, ?)",
            (episode_id, i, float(i * 5), float((i + 1) * 5), f"Segment {i}"),
        )
    await db.commit()


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
async def test_index_lectures_happy_path(app: MagicMock, db: aiosqlite.Connection) -> None:
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
        results = await index_lectures(app, 42, on_start=on_start, on_complete=on_complete)

    assert len(results) == 1
    r = results[0]
    assert r.episode_id == "ep-001"
    assert r.status == "completed"
    assert r.chunk_count > 0

    on_start.assert_called_once_with("ep-001", "Lecture 1")
    on_complete.assert_called_once_with("ep-001", r.chunk_count)

    # Verify knowledge_index row in DB
    cursor = await db.execute(
        "SELECT status, chunk_count FROM knowledge_index WHERE episode_id = 'ep-001'"
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "completed"
    assert row[1] > 0

    # Verify embedder was called with chunk texts
    mock_embedder.embed.assert_called_once()
    # Verify store received chunks and embeddings
    mock_store.add_chunks.assert_called_once()


@pytest.mark.asyncio
async def test_index_lectures_skips_completed(app: MagicMock, db: aiosqlite.Connection) -> None:
    from sophia.services.hermes_index import index_lectures

    await _insert_download(db)
    await _insert_transcription(db)
    await _insert_segments(db, count=5)

    # Pre-insert completed knowledge_index row
    await db.execute(
        "INSERT INTO knowledge_index (episode_id, module_id, chunk_count, status, indexed_at) "
        "VALUES ('ep-001', 42, 3, 'completed', datetime('now'))",
    )
    await db.commit()

    results = await index_lectures(app, 42)

    assert len(results) == 1
    assert results[0].status == "skipped"


@pytest.mark.asyncio
async def test_index_lectures_no_transcriptions(app: MagicMock, db: aiosqlite.Connection) -> None:
    from sophia.services.hermes_index import index_lectures

    results = await index_lectures(app, 42)

    assert results == []


# ---------------------------------------------------------------------------
# search_lectures — search tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_lectures(app: MagicMock, db: aiosqlite.Connection) -> None:
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
        results = await search_lectures(app, 42, "What are algorithms?")

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
async def test_search_lectures_pdf_filter_includes_material_ids(
    app: MagicMock, db: aiosqlite.Connection
) -> None:
    """With source_filter='pdf' and course_id, search includes material episode IDs."""
    from sophia.services.hermes_index import search_lectures

    await _insert_download(db, episode_id="ep-001", module_id=42, title="Lecture 1")
    # Insert course material with distinct course_id=999
    await db.execute(
        "INSERT INTO course_materials (id, course_id, module_id, name, url, status) "
        "VALUES (?, ?, ?, ?, ?, 'completed')",
        (10, 999, 42, "Slides.pdf", "https://example.com/s.pdf"),
    )
    await db.commit()

    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1, 0.2]
    mock_store = MagicMock()
    mock_store.search.return_value = []

    with (
        patch("sophia.services.hermes_index.load_hermes_config", return_value=HermesConfig()),
        patch(
            "sophia.services.hermes_index.SentenceTransformerEmbedder",
            return_value=mock_embedder,
        ),
        patch(
            "sophia.services.hermes_index.ChromaKnowledgeStore",
            return_value=mock_store,
        ),
        patch("sophia.services.hermes_index.asyncio.to_thread", side_effect=_run_sync),
    ):
        await search_lectures(app, 42, "test query", source_filter="pdf", course_id=999)

    call_kwargs = mock_store.search.call_args[1]
    episode_ids = call_kwargs["episode_ids"]
    # Must include both lecture and material episode IDs
    assert "ep-001" in episode_ids
    assert "mat-10" in episode_ids
