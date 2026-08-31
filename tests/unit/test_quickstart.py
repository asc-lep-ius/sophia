"""Tests for the sophia quickstart completion-check helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sophia.cli.quickstart import (
    _has_completed_session,
    _has_confidence,
    _has_topics,
    _is_pipeline_complete,
)

from .._sql import exec_sql

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Insert helpers ─────────────────────────────────────────────────────────


async def _insert_episode(
    db: AsyncSession,
    *,
    episode_id: str,
    module_id: int,
    status: str = "completed",
) -> None:
    await exec_sql(
        db,
        "INSERT INTO lecture_downloads"
        " (episode_id, module_id, series_id, title, track_url, track_mimetype,"
        "  file_path, status)"
        " VALUES (?, ?, 'series-1', 'Lecture', 'https://x.com/a.mp3',"
        "         'audio/mpeg', '/tmp/audio.mp3', ?)",
        (episode_id, module_id, status),
    )


async def _insert_transcription(
    db: AsyncSession, *, episode_id: str, module_id: int, status: str = "completed"
) -> None:
    await exec_sql(
        db,
        "INSERT INTO transcriptions (episode_id, module_id, status) VALUES (?, ?, ?)",
        (episode_id, module_id, status),
    )


async def _insert_knowledge_index(
    db: AsyncSession, *, episode_id: str, module_id: int, status: str = "completed"
) -> None:
    await exec_sql(
        db,
        "INSERT INTO knowledge_index (episode_id, module_id, status) VALUES (?, ?, ?)",
        (episode_id, module_id, status),
    )


async def _insert_topic(db: AsyncSession, *, topic: str, course_id: int) -> None:
    await exec_sql(
        db,
        "INSERT INTO topic_mappings (topic, course_id) VALUES (?, ?)",
        (topic, course_id),
    )


async def _insert_confidence(
    db: AsyncSession, *, topic: str, course_id: int, predicted: float = 0.5
) -> None:
    await exec_sql(
        db,
        "INSERT INTO confidence_ratings (topic, course_id, predicted) VALUES (?, ?, ?)",
        (topic, course_id, predicted),
    )


async def _insert_study_session(
    db: AsyncSession,
    *,
    course_id: int,
    topic: str,
    post_test_score: float | None = None,
) -> None:
    await exec_sql(
        db,
        "INSERT INTO study_sessions (course_id, topic, post_test_score) VALUES (?, ?, ?)",
        (course_id, topic, post_test_score),
    )


# ── _is_pipeline_complete ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pipeline_complete_empty_db(db: AsyncSession) -> None:
    assert await _is_pipeline_complete(db, 42) is False


@pytest.mark.asyncio
async def test_pipeline_complete_all_done(db: AsyncSession) -> None:
    await _insert_episode(db, episode_id="ep-1", module_id=42)
    await _insert_transcription(db, episode_id="ep-1", module_id=42)
    await _insert_knowledge_index(db, episode_id="ep-1", module_id=42)

    assert await _is_pipeline_complete(db, 42) is True


@pytest.mark.asyncio
async def test_pipeline_complete_partial(db: AsyncSession) -> None:
    await _insert_episode(db, episode_id="ep-1", module_id=42)
    await _insert_transcription(db, episode_id="ep-1", module_id=42)

    assert await _is_pipeline_complete(db, 42) is False


# ── _has_topics ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_has_topics_empty(db: AsyncSession) -> None:
    assert await _has_topics(db, 42) is False


@pytest.mark.asyncio
async def test_has_topics_present(db: AsyncSession) -> None:
    await _insert_topic(db, topic="Algebra", course_id=42)

    assert await _has_topics(db, 42) is True


# ── _has_confidence ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_has_confidence_empty(db: AsyncSession) -> None:
    assert await _has_confidence(db, 42) is False


@pytest.mark.asyncio
async def test_has_confidence_present(db: AsyncSession) -> None:
    await _insert_confidence(db, topic="Algebra", course_id=42)

    assert await _has_confidence(db, 42) is True


# ── _has_completed_session ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_has_completed_session_empty(db: AsyncSession) -> None:
    assert await _has_completed_session(db, 42) is False


@pytest.mark.asyncio
async def test_has_completed_session_complete(db: AsyncSession) -> None:
    await _insert_study_session(db, course_id=42, topic="Algebra", post_test_score=0.8)

    assert await _has_completed_session(db, 42) is True


@pytest.mark.asyncio
async def test_has_completed_session_incomplete(db: AsyncSession) -> None:
    """Session exists but post_test_score is NULL (session started, not finished)."""
    await _insert_study_session(db, course_id=42, topic="Algebra", post_test_score=None)

    assert await _has_completed_session(db, 42) is False
