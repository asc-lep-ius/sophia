"""SQLite-to-Postgres transfer: counts, checksums, coercions, and sequences."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite
import pytest
from sqlalchemy import text

from sophia.infra.persistence import run_migrations
from sophia.infra.schema import metadata
from sophia.infra.sqlite_import import (
    align_sequences,
    canonical,
    coerce_value,
    missing_tables,
    open_sqlite,
    read_rows,
    source_tables,
    transfer,
    verify,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.postgres

SEED_STATEMENTS = (
    "INSERT INTO downloads (md5, title, format, path, source, is_open_access, retail_price)"
    " VALUES ('m1', 'Linear Algebra', 'pdf', '/x.pdf', 'fixture', 1, 19.99)",
    "INSERT INTO downloads (md5, title, format, path, source, is_open_access)"
    " VALUES ('m2', 'Analysis', 'epub', '/y.epub', 'fixture', 0)",
    "INSERT INTO student_flashcards (course_id, topic, front, back, source)"
    " VALUES (12, 'Graphs', 'Q1', 'A1', 'manual')",
    "INSERT INTO student_flashcards (course_id, topic, front, back)"
    " VALUES (12, 'Graphs', 'Q2', 'A2')",
    "INSERT INTO card_review_attempts (flashcard_id, success) VALUES (1, 1)",
    "INSERT INTO card_review_attempts (flashcard_id, success) VALUES (2, 0)",
    "INSERT INTO confidence_ratings (topic, course_id, predicted, actual)"
    " VALUES ('Graphs', 12, 0.4, 0.6)",
    "INSERT INTO learning_events (event_id, course_id, user_id, event_type, occurred_at, payload)"
    " VALUES ('e1', 12, 'learner', 'prompt_shown', '2026-05-26 14:00:00', '{\"dwell_ms\": 9000}')",
    "INSERT INTO review_schedule (topic, course_id, next_review_at, difficulty, stability)"
    " VALUES ('Graphs', 12, '2026-09-01T10:00:00+00:00', 0.31, 2.5)",
)


@pytest.fixture
async def fixture_sqlite(tmp_path: Path) -> AsyncIterator[sqlite3.Connection]:
    database_path = tmp_path / "fixture.db"
    async with aiosqlite.connect(database_path) as db:
        await run_migrations(db)
        for statement in SEED_STATEMENTS:
            await db.execute(statement)
        await db.commit()

    connection = open_sqlite(database_path)
    try:
        yield connection
    finally:
        connection.close()


async def test_dry_run_writes_nothing(
    fixture_sqlite: sqlite3.Connection,
    clean_engine: AsyncEngine,
) -> None:
    report = await transfer(fixture_sqlite, clean_engine, dry_run=True)

    assert report.ok
    assert report.dry_run
    async with clean_engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM downloads")) == 0


async def test_import_transfers_every_row_with_matching_checksums(
    fixture_sqlite: sqlite3.Connection,
    clean_engine: AsyncEngine,
) -> None:
    report = await transfer(fixture_sqlite, clean_engine, dry_run=False)

    assert report.ok, [table.table for table in report.failures]
    assert report.total_rows == len(SEED_STATEMENTS)


async def test_verify_passes_after_a_clean_import(
    fixture_sqlite: sqlite3.Connection,
    clean_engine: AsyncEngine,
) -> None:
    await transfer(fixture_sqlite, clean_engine, dry_run=False)

    assert (await verify(fixture_sqlite, clean_engine)).ok


async def test_verify_catches_a_changed_value_at_an_unchanged_row_count(
    fixture_sqlite: sqlite3.Connection,
    clean_engine: AsyncEngine,
) -> None:
    """The failure a row count cannot see, which is why checksums exist."""
    await transfer(fixture_sqlite, clean_engine, dry_run=False)
    async with clean_engine.begin() as connection:
        await connection.execute(
            text("UPDATE downloads SET is_open_access = false WHERE md5 = 'm1'")
        )

    report = await verify(fixture_sqlite, clean_engine)

    failures = {table.table for table in report.failures}
    assert failures == {"downloads"}
    downloads = next(table for table in report.tables if table.table == "downloads")
    assert downloads.rows_match
    assert not downloads.checksums_match


async def test_verify_catches_a_missing_row(
    fixture_sqlite: sqlite3.Connection,
    clean_engine: AsyncEngine,
) -> None:
    await transfer(fixture_sqlite, clean_engine, dry_run=False)
    async with clean_engine.begin() as connection:
        await connection.execute(text("DELETE FROM downloads WHERE md5 = 'm2'"))

    report = await verify(fixture_sqlite, clean_engine)

    assert {table.table for table in report.failures} == {"downloads"}


async def test_integer_booleans_become_real_booleans(
    fixture_sqlite: sqlite3.Connection,
    clean_engine: AsyncEngine,
) -> None:
    await transfer(fixture_sqlite, clean_engine, dry_run=False)

    async with clean_engine.connect() as connection:
        result = await connection.execute(
            text("SELECT md5, is_open_access FROM downloads ORDER BY md5")
        )
        rows = result.all()

    assert [(row[0], row[1]) for row in rows] == [("m1", True), ("m2", False)]


async def test_naive_timestamps_are_read_as_utc(
    fixture_sqlite: sqlite3.Connection,
    clean_engine: AsyncEngine,
) -> None:
    """SQLite's CURRENT_TIMESTAMP is UTC without an offset; nothing is guessed."""
    await transfer(fixture_sqlite, clean_engine, dry_run=False)

    async with clean_engine.connect() as connection:
        occurred_at = await connection.scalar(
            text("SELECT occurred_at FROM learning_events WHERE event_id = 'e1'")
        )

    assert occurred_at == datetime(2026, 5, 26, 14, 0, tzinfo=UTC)


async def test_sequences_are_advanced_past_imported_ids(
    fixture_sqlite: sqlite3.Connection,
    clean_engine: AsyncEngine,
) -> None:
    """Without this the first post-migration insert collides with imported data."""
    await transfer(fixture_sqlite, clean_engine, dry_run=False)

    async with clean_engine.begin() as connection:
        new_id = await connection.scalar(
            text(
                "INSERT INTO student_flashcards (course_id, topic, front, back) "
                "VALUES (12, 'Graphs', 'Q3', 'A3') RETURNING id"
            )
        )

    assert new_id == 3


async def test_sequence_alignment_is_safe_on_an_empty_database(
    clean_engine: AsyncEngine,
) -> None:
    aligned = await align_sequences(clean_engine)

    assert aligned["student_flashcards"] == 1


async def test_source_tables_skip_sqlite_bookkeeping(
    fixture_sqlite: sqlite3.Connection,
) -> None:
    tables = source_tables(fixture_sqlite)

    assert "schema_version" not in tables
    assert "sqlite_sequence" not in tables
    assert set(tables) <= set(metadata.tables)


async def test_source_tables_are_returned_in_dependency_order(
    fixture_sqlite: sqlite3.Connection,
) -> None:
    """Children after parents, or the foreign keys reject the import."""
    tables = source_tables(fixture_sqlite)

    assert tables.index("student_flashcards") < tables.index("card_review_attempts")
    assert tables.index("lecture_downloads") < tables.index("transcriptions")
    assert tables.index("content_provenance") < tables.index("content_source_spans")


async def test_unmodelled_source_tables_are_reported(
    fixture_sqlite: sqlite3.Connection,
) -> None:
    """A table nobody modelled is data the migration would silently drop."""
    fixture_sqlite.close()

    assert missing_tables(_sqlite_with_extra_table()) == ["legacy_notes"]


def _sqlite_with_extra_table() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE legacy_notes (id INTEGER PRIMARY KEY, body TEXT)")
    connection.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY)")
    return connection


def test_canonical_renders_values_engine_independently() -> None:
    assert canonical(None) == "\\N"
    assert canonical(True) == "t"
    assert canonical(False) == "f"
    assert canonical(3) == "3"
    assert canonical(0.5) == "0.5"
    assert canonical(datetime(2026, 5, 26, 14, 0, tzinfo=UTC)) == "2026-05-26T14:00:00+00:00"


def test_coercion_maps_sqlite_storage_to_declared_types() -> None:
    downloads = metadata.tables["downloads"]
    learning_events = metadata.tables["learning_events"]

    assert coerce_value(1, downloads.columns["is_open_access"]) is True
    assert coerce_value(0, downloads.columns["is_open_access"]) is False
    assert coerce_value(None, downloads.columns["is_open_access"]) is None
    assert coerce_value("2026-05-26 14:00:00", learning_events.columns["occurred_at"]) == datetime(
        2026, 5, 26, 14, 0, tzinfo=UTC
    )


async def test_rows_are_read_in_primary_key_order(
    fixture_sqlite: sqlite3.Connection,
) -> None:
    """Both sides must order identically or the checksums compare noise."""
    rows = read_rows(fixture_sqlite, metadata.tables["downloads"])

    assert [row["md5"] for row in rows] == ["m1", "m2"]
