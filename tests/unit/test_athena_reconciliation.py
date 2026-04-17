"""Tests for the topic reconciliation engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite
import pytest

from sophia.infra.persistence import run_migrations
from sophia.services.athena_reconciliation import (
    FUZZY_MATCH_THRESHOLD,
    ReconciliationResult,
    format_reconciliation_message,
    reconcile_manual_topics,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


# ── Fixtures & helpers ─────────────────────────────────────────────────────


@pytest.fixture
async def db() -> AsyncGenerator[aiosqlite.Connection, None]:
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("PRAGMA foreign_keys=ON")
    await run_migrations(conn)
    yield conn
    await conn.close()


async def _insert_topic(
    db: aiosqlite.Connection,
    topic: str,
    course_id: int,
    source: str = "lecture",
) -> None:
    await db.execute(
        "INSERT INTO topic_mappings (topic, course_id, source) VALUES (?, ?, ?)",
        (topic, course_id, source),
    )
    await db.commit()


COURSE = 42


# ── Matching tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_match(db: aiosqlite.Connection) -> None:
    await _insert_topic(db, "Algebra", COURSE, "manual")
    await _insert_topic(db, "Algebra", COURSE, "lecture")

    result = await reconcile_manual_topics(db, COURSE)

    assert len(result.matched) == 1
    manual, moodle, score = result.matched[0]
    assert manual == "Algebra"
    assert moodle == "Algebra"
    assert score == pytest.approx(1.0)
    assert result.unmatched_manual == []
    assert result.new_moodle == []


@pytest.mark.asyncio
async def test_fuzzy_match(db: aiosqlite.Connection) -> None:
    await _insert_topic(db, "Lin Algebra", COURSE, "manual")
    await _insert_topic(db, "Linear Algebra", COURSE, "lecture")

    result = await reconcile_manual_topics(db, COURSE)

    assert len(result.matched) == 1
    _, _, score = result.matched[0]
    assert score >= FUZZY_MATCH_THRESHOLD


@pytest.mark.asyncio
async def test_case_insensitive(db: aiosqlite.Connection) -> None:
    await _insert_topic(db, "algebra", COURSE, "manual")
    await _insert_topic(db, "Algebra", COURSE, "lecture")

    result = await reconcile_manual_topics(db, COURSE)

    assert len(result.matched) == 1
    assert result.matched[0][2] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_no_match_below_threshold(db: aiosqlite.Connection) -> None:
    await _insert_topic(db, "Philosophy", COURSE, "manual")
    await _insert_topic(db, "Algebra", COURSE, "lecture")

    result = await reconcile_manual_topics(db, COURSE)

    assert result.matched == []
    assert "Philosophy" in result.unmatched_manual
    assert "Algebra" in result.new_moodle


@pytest.mark.asyncio
async def test_new_moodle_topics(db: aiosqlite.Connection) -> None:
    await _insert_topic(db, "Algebra", COURSE, "manual")
    await _insert_topic(db, "Algebra", COURSE, "lecture")
    await _insert_topic(db, "Calculus", COURSE, "lecture")

    result = await reconcile_manual_topics(db, COURSE)

    assert len(result.matched) == 1
    assert "Calculus" in result.new_moodle


# ── Edge cases ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_no_manual_topics_is_noop(db: aiosqlite.Connection) -> None:
    await _insert_topic(db, "Algebra", COURSE, "lecture")

    result = await reconcile_manual_topics(db, COURSE)

    assert result == ReconciliationResult(matched=[], unmatched_manual=[], new_moodle=[])


@pytest.mark.asyncio
async def test_no_moodle_topics(db: aiosqlite.Connection) -> None:
    await _insert_topic(db, "Algebra", COURSE, "manual")
    await _insert_topic(db, "Calculus", COURSE, "manual")

    result = await reconcile_manual_topics(db, COURSE)

    assert result.matched == []
    assert set(result.unmatched_manual) == {"Algebra", "Calculus"}


@pytest.mark.asyncio
async def test_idempotent(db: aiosqlite.Connection) -> None:
    await _insert_topic(db, "Algebra", COURSE, "manual")
    await _insert_topic(db, "Algebra", COURSE, "lecture")

    await reconcile_manual_topics(db, COURSE)
    await reconcile_manual_topics(db, COURSE)

    cursor = await db.execute(
        "SELECT COUNT(*) FROM topic_reconciliations WHERE course_id = ?",
        (COURSE,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1


@pytest.mark.asyncio
async def test_manual_topics_preserved(db: aiosqlite.Connection) -> None:
    await _insert_topic(db, "Algebra", COURSE, "manual")
    await _insert_topic(db, "Algebra", COURSE, "lecture")

    await reconcile_manual_topics(db, COURSE)

    cursor = await db.execute(
        "SELECT COUNT(*) FROM topic_mappings WHERE course_id = ? AND source = 'manual'",
        (COURSE,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 1


# ── Message formatting ─────────────────────────────────────────────────────


def test_format_reconciliation_message_all_matched() -> None:
    result = ReconciliationResult(
        matched=[("Algebra", "Algebra", 1.0), ("Calculus", "Calculus", 1.0)],
        unmatched_manual=[],
        new_moodle=[],
    )
    msg = format_reconciliation_message(result)

    assert "2" in msg
    assert "matched" in msg.lower()


def test_format_reconciliation_message_with_gaps() -> None:
    result = ReconciliationResult(
        matched=[("Algebra", "Algebra", 1.0)],
        unmatched_manual=["Philosophy"],
        new_moodle=["Calculus", "Statistics"],
    )
    msg = format_reconciliation_message(result)

    assert "1" in msg  # 1 matched or 1 unmatched
    assert "Philosophy" in msg or "1 topic" in msg.lower()
    assert "Calculus" in msg or "Statistics" in msg or "2 topic" in msg.lower()


def test_format_reconciliation_message_empty() -> None:
    result = ReconciliationResult(matched=[], unmatched_manual=[], new_moodle=[])
    msg = format_reconciliation_message(result)

    assert msg == ""


# ── Hook integration test ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconciliation_runs_after_topic_extraction(db: aiosqlite.Connection) -> None:
    """After extract_topics_from_lectures commits Moodle topics, reconcile_manual_topics runs."""
    # Pre-populate manual predictions
    await _insert_topic(db, "Algebra", COURSE, "manual")
    await _insert_topic(db, "Calculus", COURSE, "manual")
    # Simulate Moodle topics already extracted
    await _insert_topic(db, "Algebra", COURSE, "lecture")
    await _insert_topic(db, "Statistics", COURSE, "lecture")

    # Run reconciliation (this is what the hook calls)
    result = await reconcile_manual_topics(db, COURSE)

    assert len(result.matched) == 1
    assert result.matched[0][0] == "Algebra"
    assert "Calculus" in result.unmatched_manual
    assert "Statistics" in result.new_moodle

    # Verify persisted to topic_reconciliations table
    cursor = await db.execute(
        "SELECT manual_topic, moodle_topic FROM topic_reconciliations WHERE course_id = ?",
        (COURSE,),
    )
    rows = list(await cursor.fetchall())
    assert len(rows) == 1
    assert rows[0][0] == "Algebra"


# ── Storage key test ───────────────────────────────────────────────────────


def test_reconciliation_dismissed_key_exists() -> None:
    from sophia.gui.state.storage_map import USER_RECONCILIATION_DISMISSED

    assert USER_RECONCILIATION_DISMISSED == "reconciliation_dismissed"
