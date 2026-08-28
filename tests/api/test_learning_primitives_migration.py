"""Persistence shape for the Phase 2 learning primitives (migration 024)."""

from __future__ import annotations

import shutil
from pathlib import Path

import aiosqlite
import pytest

from sophia.infra.persistence import run_migrations

REPO_ROOT = Path(__file__).parents[2]
MIGRATIONS_DIR = REPO_ROOT / "src" / "sophia" / "infra" / "migrations"
LEARNING_PRIMITIVES_VERSION = 24
NEW_TABLES = (
    "content_provenance",
    "content_source_spans",
    "content_translations",
    "generated_questions",
    "learning_events",
    "learning_path_settings",
    "question_attempts",
)


@pytest.fixture
async def db():
    async with aiosqlite.connect(":memory:") as connection:
        await connection.execute("PRAGMA foreign_keys=ON")
        await run_migrations(connection)
        yield connection


async def test_migration_creates_every_learning_primitive_table(
    db: aiosqlite.Connection,
) -> None:
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    tables = {str(row[0]) for row in await cursor.fetchall()}

    assert set(NEW_TABLES) <= tables


async def test_event_ids_are_unique(db: aiosqlite.Connection) -> None:
    """The uniqueness constraint is what makes a retried batch idempotent."""
    insert = (
        "INSERT INTO learning_events (event_id, course_id, user_id, event_type, occurred_at) "
        "VALUES ('event-1', 12, 'learner', 'prompt_shown', '2026-05-26T14:00:00+00:00')"
    )
    await db.execute(insert)

    with pytest.raises(aiosqlite.IntegrityError):
        await db.execute(insert)


async def test_provenance_is_unique_per_content_item(db: aiosqlite.Connection) -> None:
    insert = (
        "INSERT INTO content_provenance (content_kind, content_id, course_id, generated_by) "
        "VALUES ('question', 'question-1', 12, 'model')"
    )
    await db.execute(insert)

    with pytest.raises(aiosqlite.IntegrityError):
        await db.execute(insert)


async def test_source_spans_are_removed_with_their_provenance(
    db: aiosqlite.Connection,
) -> None:
    await db.execute(
        "INSERT INTO content_provenance (id, content_kind, content_id, course_id, generated_by) "
        "VALUES (1, 'question', 'question-1', 12, 'model')"
    )
    await db.execute(
        "INSERT INTO content_source_spans (provenance_id, content_item_id) VALUES (1, 'item-1')"
    )

    await db.execute("DELETE FROM content_provenance WHERE id = 1")

    cursor = await db.execute("SELECT COUNT(*) FROM content_source_spans")
    assert await cursor.fetchone() == (0,)


async def test_content_origin_accepts_new_values_without_a_migration(
    db: aiosqlite.Connection,
) -> None:
    """The reserved discriminator must not be pinned by a CHECK constraint."""
    await db.execute(
        "INSERT INTO content_provenance "
        "(content_kind, content_id, course_id, generated_by, content_origin) "
        "VALUES ('question', 'question-1', 12, 'model', 'some-future-source')"
    )

    cursor = await db.execute("SELECT content_origin FROM content_provenance")
    assert await cursor.fetchone() == ("some-future-source",)


async def test_translations_are_unique_per_content_item_and_language(
    db: aiosqlite.Connection,
) -> None:
    insert = (
        "INSERT INTO content_translations (content_kind, content_id, language, course_id) "
        "VALUES ('question', 'question-1', 'en', 12)"
    )
    await db.execute(insert)

    with pytest.raises(aiosqlite.IntegrityError):
        await db.execute(insert)


async def test_migration_preserves_pre_existing_rows(tmp_path: Path) -> None:
    historical = tmp_path / "migrations"
    historical.mkdir()
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if int(sql_file.stem.split("_")[0]) < LEARNING_PRIMITIVES_VERSION:
            shutil.copy(sql_file, historical / sql_file.name)

    async with aiosqlite.connect(":memory:") as db:
        await run_migrations(db, migrations_dir=historical)
        await db.execute(
            "INSERT INTO student_flashcards (course_id, topic, front, back) "
            "VALUES (12, 'Graphs', 'Q', 'A')"
        )
        await db.commit()

        await run_migrations(db)

        cursor = await db.execute("SELECT topic FROM student_flashcards WHERE course_id = 12")
        assert await cursor.fetchone() == ("Graphs",)
        cursor = await db.execute("SELECT MAX(version) FROM schema_version")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] >= LEARNING_PRIMITIVES_VERSION
