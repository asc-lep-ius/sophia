"""Tests for the Athena study service — topic extraction and linking orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite
import pytest

from sophia.domain.models import (
    KnowledgeChunk,
    TopicSource,
)
from sophia.infra.persistence import run_migrations

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
async def db():
    db_conn = await aiosqlite.connect(":memory:")
    await db_conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(db_conn)
    yield db_conn
    await db_conn.close()


@pytest.fixture
def hermes_config(tmp_path: Path) -> None:
    """Write a minimal hermes.toml so load_hermes_config finds it."""
    config_file = tmp_path / "config" / "hermes.toml"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(
        "[whisper]\n"
        'model = "large-v3"\n'
        'device = "cpu"\n'
        'compute_type = "float32"\n'
        "\n"
        "[llm]\n"
        'provider = "github"\n'
        'model = "openai/gpt-4o"\n'
        'api_key_env = "GITHUB_TOKEN"\n'
        "\n"
        "[embeddings]\n"
        'provider = "local"\n'
        'model = "intfloat/multilingual-e5-large"\n'
    )


@pytest.fixture
def app(db: aiosqlite.Connection, tmp_path: Path, hermes_config: None) -> MagicMock:
    mock = MagicMock()
    mock.db = db
    mock.settings.config_dir = tmp_path / "config"
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
            (episode_id, i, float(i * 5), float((i + 1) * 5), f"Segment about topic {i}"),
        )
    await db.commit()


# ---------------------------------------------------------------------------
# get_course_topics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_course_topics_empty(app: MagicMock) -> None:
    from sophia.services.athena_study import get_course_topics

    result = await get_course_topics(app, course_id=99)
    assert result == []


@pytest.mark.asyncio
async def test_get_course_topics_returns_persisted(
    app: MagicMock, db: aiosqlite.Connection
) -> None:
    from sophia.services.athena_study import get_course_topics

    await db.execute(
        "INSERT INTO topic_mappings (topic, course_id, source, frequency) VALUES (?, ?, ?, ?)",
        ("Linear Algebra", 42, "lecture", 2),
    )
    await db.execute(
        "INSERT INTO topic_mappings (topic, course_id, source, frequency) VALUES (?, ?, ?, ?)",
        ("Calculus", 42, "lecture", 1),
    )
    await db.commit()

    result = await get_course_topics(app, course_id=42)
    assert len(result) == 2
    assert result[0].topic == "Linear Algebra"
    assert result[0].frequency == 2


# ---------------------------------------------------------------------------
# extract_topics_from_lectures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_topics_no_transcripts(app: MagicMock) -> None:
    from sophia.services.athena_study import extract_topics_from_lectures

    result = await extract_topics_from_lectures(app, module_id=42)
    assert result == []


@pytest.mark.asyncio
async def test_extract_topics_from_lectures_success(
    app: MagicMock, db: aiosqlite.Connection
) -> None:
    from sophia.services.athena_study import extract_topics_from_lectures

    await _insert_download(db, episode_id="ep-001", module_id=42)
    await _insert_transcription(db, episode_id="ep-001", module_id=42)
    await _insert_segments(db, episode_id="ep-001", count=5)

    mock_extractor = AsyncMock()
    mock_extractor.extract_topics = AsyncMock(return_value=["Linear Algebra", "Matrix Operations"])

    with patch(
        "sophia.services.athena_study._create_topic_extractor",
        return_value=mock_extractor,
    ):
        result = await extract_topics_from_lectures(app, module_id=42)

    assert len(result) == 2
    assert result[0].topic == "Linear Algebra"
    assert result[0].source == TopicSource.LECTURE

    # Verify persisted to DB
    from sophia.services.athena_study import get_course_topics

    # Get course_id from the lecture_downloads
    cursor = await db.execute(
        "SELECT DISTINCT module_id FROM lecture_downloads WHERE module_id = 42"
    )
    row = await cursor.fetchone()
    assert row is not None

    # Topics should be in the DB now — use course_id from result
    topics = await get_course_topics(app, course_id=result[0].course_id)
    assert len(topics) == 2


@pytest.mark.asyncio
async def test_extract_topics_idempotent(app: MagicMock, db: aiosqlite.Connection) -> None:
    """Re-running extraction upserts but doesn't duplicate topics."""
    from sophia.services.athena_study import extract_topics_from_lectures

    await _insert_download(db, episode_id="ep-001", module_id=42)
    await _insert_transcription(db, episode_id="ep-001", module_id=42)
    await _insert_segments(db, episode_id="ep-001", count=3)

    mock_extractor = AsyncMock()
    mock_extractor.extract_topics = AsyncMock(return_value=["Sorting"])

    with patch(
        "sophia.services.athena_study._create_topic_extractor",
        return_value=mock_extractor,
    ):
        await extract_topics_from_lectures(app, module_id=42)
        # Run again — should upsert, not duplicate
        await extract_topics_from_lectures(app, module_id=42)

    cursor = await db.execute("SELECT COUNT(*) FROM topic_mappings WHERE topic = 'Sorting'")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1


# ---------------------------------------------------------------------------
# link_topics_to_lectures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_link_topics_empty_topics(app: MagicMock) -> None:
    from sophia.services.athena_study import link_topics_to_lectures

    result = await link_topics_to_lectures(app, course_id=42, module_id=42, topics=[])
    assert result == {}


@pytest.mark.asyncio
async def test_link_topics_to_lectures_success(app: MagicMock, db: aiosqlite.Connection) -> None:
    from sophia.services.athena_study import link_topics_to_lectures

    await _insert_download(db, episode_id="ep-001", module_id=42)

    mock_chunk = KnowledgeChunk(
        chunk_id="ep-001_0",
        episode_id="ep-001",
        chunk_index=0,
        text="Introduction to sorting algorithms",
        start_time=0.0,
        end_time=15.0,
    )

    mock_embedder = MagicMock()
    mock_embedder.embed_query.return_value = [0.1, 0.2, 0.3]

    mock_store = MagicMock()
    mock_store.search.return_value = [(mock_chunk, 0.92)]

    with (
        patch(
            "sophia.services.athena_study._create_embedder",
            return_value=mock_embedder,
        ),
        patch(
            "sophia.services.athena_study._create_store",
            return_value=mock_store,
        ),
        patch(
            "sophia.services.athena_study.asyncio.to_thread",
            side_effect=lambda fn, *a, **kw: fn(*a, **kw),
        ),
    ):
        result = await link_topics_to_lectures(app, course_id=42, module_id=42, topics=["Sorting"])

    assert "Sorting" in result
    assert len(result["Sorting"]) == 1
    assert result["Sorting"][0][1] == pytest.approx(0.92)

    # Verify persisted to DB
    cursor = await db.execute(
        "SELECT topic, chunk_id, score FROM topic_lecture_links WHERE course_id = 42"
    )
    rows = await cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "Sorting"
    assert rows[0][1] == "ep-001_0"
