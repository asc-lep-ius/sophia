"""Tests for the sophia quickstart completion-check helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite
import pytest

from sophia.cli.quickstart import (
    _has_completed_session,
    _has_confidence,
    _has_topics,
    _is_pipeline_complete,
)
from sophia.infra.persistence import run_migrations

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def db() -> AsyncGenerator[aiosqlite.Connection, None]:
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(conn)
    yield conn
    await conn.close()


# ── Insert helpers ─────────────────────────────────────────────────────────


async def _insert_episode(
    db: aiosqlite.Connection,
    *,
    episode_id: str,
    module_id: int,
    status: str = "completed",
) -> None:
    await db.execute(
        "INSERT INTO lecture_downloads"
        " (episode_id, module_id, series_id, title, track_url, track_mimetype,"
        "  file_path, status)"
        " VALUES (?, ?, 'series-1', 'Lecture', 'https://x.com/a.mp3',"
        "         'audio/mpeg', '/tmp/audio.mp3', ?)",
        (episode_id, module_id, status),
    )
    await db.commit()


async def _insert_transcription(
    db: aiosqlite.Connection, *, episode_id: str, module_id: int, status: str = "completed"
) -> None:
    await db.execute(
        "INSERT INTO transcriptions (episode_id, module_id, status) VALUES (?, ?, ?)",
        (episode_id, module_id, status),
    )
    await db.commit()


async def _insert_knowledge_index(
    db: aiosqlite.Connection, *, episode_id: str, module_id: int, status: str = "completed"
) -> None:
    await db.execute(
        "INSERT INTO knowledge_index (episode_id, module_id, status) VALUES (?, ?, ?)",
        (episode_id, module_id, status),
    )
    await db.commit()


async def _insert_topic(db: aiosqlite.Connection, *, topic: str, course_id: int) -> None:
    await db.execute(
        "INSERT INTO topic_mappings (topic, course_id) VALUES (?, ?)",
        (topic, course_id),
    )
    await db.commit()


async def _insert_confidence(
    db: aiosqlite.Connection, *, topic: str, course_id: int, predicted: float = 0.5
) -> None:
    await db.execute(
        "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
        (topic, course_id, predicted),
    )
    await db.commit()


async def _insert_study_session(
    db: aiosqlite.Connection,
    *,
    course_id: int,
    topic: str,
    post_test_score: float | None = None,
) -> None:
    await db.execute(
        "INSERT INTO study_sessions (course_id, topic, post_test_score) VALUES (?, ?, ?)",
        (course_id, topic, post_test_score),
    )
    await db.commit()


# ── _is_pipeline_complete ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_complete_empty_db(db: aiosqlite.Connection) -> None:
    assert await _is_pipeline_complete(db, 42) is False


@pytest.mark.asyncio
async def test_pipeline_complete_all_done(db: aiosqlite.Connection) -> None:
    await _insert_episode(db, episode_id="ep-1", module_id=42)
    await _insert_transcription(db, episode_id="ep-1", module_id=42)
    await _insert_knowledge_index(db, episode_id="ep-1", module_id=42)

    assert await _is_pipeline_complete(db, 42) is True


@pytest.mark.asyncio
async def test_pipeline_complete_partial(db: aiosqlite.Connection) -> None:
    await _insert_episode(db, episode_id="ep-1", module_id=42)
    await _insert_transcription(db, episode_id="ep-1", module_id=42)

    assert await _is_pipeline_complete(db, 42) is False


# ── _has_topics ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_has_topics_empty(db: aiosqlite.Connection) -> None:
    assert await _has_topics(db, 42) is False


@pytest.mark.asyncio
async def test_has_topics_present(db: aiosqlite.Connection) -> None:
    await _insert_topic(db, topic="Algebra", course_id=42)

    assert await _has_topics(db, 42) is True


# ── _has_confidence ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_has_confidence_empty(db: aiosqlite.Connection) -> None:
    assert await _has_confidence(db, 42) is False


@pytest.mark.asyncio
async def test_has_confidence_present(db: aiosqlite.Connection) -> None:
    await _insert_confidence(db, topic="Algebra", course_id=42)

    assert await _has_confidence(db, 42) is True


# ── _has_completed_session ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_has_completed_session_empty(db: aiosqlite.Connection) -> None:
    assert await _has_completed_session(db, 42) is False


@pytest.mark.asyncio
async def test_has_completed_session_complete(db: aiosqlite.Connection) -> None:
    await _insert_study_session(db, course_id=42, topic="Algebra", post_test_score=0.8)

    assert await _has_completed_session(db, 42) is True


@pytest.mark.asyncio
async def test_has_completed_session_incomplete(db: aiosqlite.Connection) -> None:
    """Session exists but post_test_score is NULL (session started, not finished)."""
    await _insert_study_session(db, course_id=42, topic="Algebra", post_test_score=None)

    assert await _has_completed_session(db, 42) is False
