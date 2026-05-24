"""Tenancy migration coverage for persisted SQLite tables."""

from __future__ import annotations

import shutil
from pathlib import Path

import aiosqlite
import pytest

from sophia.infra.persistence import run_migrations

REPO_ROOT = Path(__file__).parents[2]
MIGRATIONS_DIR = REPO_ROOT / "src" / "sophia" / "infra" / "migrations"
TENANCY_MIGRATION_VERSION = 22

TABLES_WITH_EXISTING_COURSE_ID = {
    "confidence_ratings",
    "course_materials",
    "deadline_cache",
    "discovered_references",
    "effort_estimates",
    "review_schedule",
    "student_flashcards",
    "study_sessions",
    "topic_lecture_links",
    "topic_mappings",
    "topic_reconciliations",
}
TABLES_REQUIRING_COURSE_ID = {
    "active_timers",
    "book_cache",
    "card_review_attempts",
    "deadline_reflections",
    "downloads",
    "knowledge_index",
    "lecture_downloads",
    "lecture_modules",
    "metacognition_log",
    "scheduled_jobs",
    "self_explanations",
    "time_entries",
    "transcript_segments",
    "transcriptions",
}
PERSISTED_TABLES = TABLES_WITH_EXISTING_COURSE_ID | TABLES_REQUIRING_COURSE_ID


@pytest.mark.asyncio
async def test_tenancy_columns_apply_to_fresh_database() -> None:
    async with aiosqlite.connect(":memory:") as db:
        await run_migrations(db)

        for table_name in sorted(PERSISTED_TABLES):
            column_names = await _table_columns(db, table_name)
            columns = await _table_column_info(db, table_name)
            assert column_names.count("org_id") == 1, table_name
            assert columns["org_id"] == ("TEXT", True, "'default'"), table_name

            course_id_count = column_names.count("course_id")
            assert course_id_count == 1, table_name
            if table_name in TABLES_REQUIRING_COURSE_ID:
                assert columns["course_id"] == ("TEXT", True, "'default'"), table_name

        schema_columns = await _table_columns(db, "schema_version")
        assert "org_id" not in schema_columns
        assert "course_id" not in schema_columns

        cursor = await db.execute("SELECT MAX(version) FROM schema_version")
        row = await cursor.fetchone()
        assert row == (TENANCY_MIGRATION_VERSION,)


@pytest.mark.asyncio
async def test_tenancy_migration_preserves_version_21_rows(tmp_path: Path) -> None:
    historical_migrations = tmp_path / "migrations"
    _copy_migrations_through(historical_migrations, version=21)

    async with aiosqlite.connect(":memory:") as db:
        await run_migrations(db, migrations_dir=historical_migrations)
        await db.execute(
            """
            INSERT INTO downloads (md5, title, format, path, source)
            VALUES ('book-md5', 'Linear Algebra', 'pdf', '/tmp/book.pdf', 'fixture')
            """
        )
        await db.execute(
            """
            INSERT INTO lecture_downloads (
                episode_id, module_id, title, track_url, track_mimetype
            )
            VALUES ('episode-1', 7, 'Lecture 1', 'https://example.test/1.mp4', 'video/mp4')
            """
        )
        await db.execute(
            """
            INSERT INTO topic_mappings (topic, course_id, source)
            VALUES ('eigenvalues', 42, 'lecture')
            """
        )
        await db.commit()

        await run_migrations(db)

        cursor = await db.execute(
            "SELECT title, org_id, course_id FROM downloads WHERE md5 = 'book-md5'"
        )
        assert await cursor.fetchone() == ("Linear Algebra", "default", "default")

        cursor = await db.execute(
            """
            SELECT title, module_id, org_id, course_id
            FROM lecture_downloads
            WHERE episode_id = 'episode-1'
            """
        )
        assert await cursor.fetchone() == ("Lecture 1", 7, "default", "default")

        cursor = await db.execute(
            "SELECT topic, course_id, org_id FROM topic_mappings WHERE topic = 'eigenvalues'"
        )
        assert await cursor.fetchone() == ("eigenvalues", 42, "default")

        topic_columns = await _table_columns(db, "topic_mappings")
        assert topic_columns.count("course_id") == 1


async def _table_columns(db: aiosqlite.Connection, table_name: str) -> list[str]:
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    return [str(row[1]) for row in await cursor.fetchall()]


async def _table_column_info(
    db: aiosqlite.Connection,
    table_name: str,
) -> dict[str, tuple[str, bool, str | None]]:
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    return {
        str(row[1]): (str(row[2]), bool(row[3]), None if row[4] is None else str(row[4]))
        for row in await cursor.fetchall()
    }


def _copy_migrations_through(destination: Path, *, version: int) -> None:
    destination.mkdir(parents=True)
    for sql_file in sorted(MIGRATIONS_DIR.glob("*.sql")):
        migration_version = int(sql_file.stem.split("_")[0])
        if migration_version <= version:
            shutil.copy2(sql_file, destination / sql_file.name)
