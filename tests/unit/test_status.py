"""Tests for the sophia status dashboard command."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite
import pytest

from sophia.cli.status import _fetch_course_stats, _frac_cell
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


async def _insert_flashcard(db: aiosqlite.Connection, *, course_id: int) -> None:
    await db.execute(
        "INSERT INTO student_flashcards (course_id, topic, front, back)"
        " VALUES (?, 'Topic A', 'Q?', 'A.')",
        (course_id,),
    )
    await db.commit()


async def _insert_review(
    db: aiosqlite.Connection,
    *,
    course_id: int,
    topic: str,
    next_review_at: str,
) -> None:
    await db.execute(
        "INSERT INTO review_schedule (topic, course_id, next_review_at) VALUES (?, ?, ?)",
        (topic, course_id, next_review_at),
    )
    await db.commit()


# ── _frac_cell ──────────────────────────────────────────────────────────────


class TestFracCell:
    def test_zero_total(self) -> None:
        assert "[dim]" in _frac_cell(0, 0)

    def test_complete(self) -> None:
        result = _frac_cell(5, 5)
        assert "green" in result
        assert "5/5" in result

    def test_partial(self) -> None:
        result = _frac_cell(3, 5)
        assert "yellow" in result
        assert "3/5" in result

    def test_zero_of_nonzero(self) -> None:
        result = _frac_cell(0, 5)
        assert "0/5" in result
        assert "dim" in result


# ── _fetch_course_stats ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_empty_returns_empty(db: aiosqlite.Connection) -> None:
    result = await _fetch_course_stats(db)
    assert result == []


@pytest.mark.asyncio
async def test_fetch_single_module(db: aiosqlite.Connection) -> None:
    await _insert_episode(db, episode_id="ep-1", module_id=42)
    await _insert_transcription(db, episode_id="ep-1", module_id=42)
    await _insert_knowledge_index(db, episode_id="ep-1", module_id=42)
    await _insert_topic(db, topic="Algebra", course_id=42)
    await _insert_flashcard(db, course_id=42)

    rows = await _fetch_course_stats(db)

    assert len(rows) == 1
    row = rows[0]
    assert row["module_id"] == 42
    assert row["total_lectures"] == 1
    assert row["downloaded"] == 1
    assert row["transcribed"] == 1
    assert row["indexed"] == 1
    assert row["topics"] == 1
    assert row["flashcards"] == 1
    assert row["due_today"] == 0
    assert row["next_review"] is None


@pytest.mark.asyncio
async def test_fetch_partial_pipeline(db: aiosqlite.Connection) -> None:
    """Module with 2 episodes but only one transcribed and indexed."""
    await _insert_episode(db, episode_id="ep-1", module_id=10)
    await _insert_episode(db, episode_id="ep-2", module_id=10)
    await _insert_transcription(db, episode_id="ep-1", module_id=10)
    await _insert_knowledge_index(db, episode_id="ep-1", module_id=10)

    rows = await _fetch_course_stats(db)

    assert len(rows) == 1
    row = rows[0]
    assert row["total_lectures"] == 2
    assert row["downloaded"] == 2
    assert row["transcribed"] == 1
    assert row["indexed"] == 1


@pytest.mark.asyncio
async def test_fetch_multiple_modules(db: aiosqlite.Connection) -> None:
    for mod in (1, 2):
        await _insert_episode(db, episode_id=f"ep-{mod}", module_id=mod)

    rows = await _fetch_course_stats(db)

    assert len(rows) == 2
    assert {r["module_id"] for r in rows} == {1, 2}


@pytest.mark.asyncio
async def test_fetch_due_today(db: aiosqlite.Connection) -> None:
    await _insert_episode(db, episode_id="ep-1", module_id=5)
    await _insert_review(
        db,
        course_id=5,
        topic="Statistics",
        next_review_at="2000-01-01 00:00:00",  # always in the past
    )

    rows = await _fetch_course_stats(db)

    assert rows[0]["due_today"] == 1


@pytest.mark.asyncio
async def test_fetch_next_review_date(db: aiosqlite.Connection) -> None:
    await _insert_episode(db, episode_id="ep-1", module_id=7)
    await _insert_review(
        db,
        course_id=7,
        topic="Calculus",
        next_review_at="2099-12-31 00:00:00",  # always in the future
    )

    rows = await _fetch_course_stats(db)

    assert rows[0]["due_today"] == 0
    assert rows[0]["next_review"] is not None
    assert "2099" in str(rows[0]["next_review"])
