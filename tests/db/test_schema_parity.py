"""The Postgres metadata is a faithful port of the SQLite schema.

Needs no Postgres: it compares the SQLite schema the numbered migrations build
against the SQLAlchemy metadata Alembic generates from. A column dropped or
misspelled during the port survives every other test in this suite — the
migration would copy 32 tables, match 32 row counts, and quietly lose a field.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite
import pytest

from sophia.infra.persistence import run_migrations
from sophia.infra.schema import metadata
from sophia.infra.sqlite_import import SKIPPED_SOURCE_TABLES

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture
async def sqlite_db() -> AsyncIterator[aiosqlite.Connection]:
    async with aiosqlite.connect(":memory:") as db:
        await run_migrations(db)
        yield db


async def sqlite_tables(db: aiosqlite.Connection) -> set[str]:
    cursor = await db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {str(row[0]) for row in await cursor.fetchall()} - set(SKIPPED_SOURCE_TABLES)


async def sqlite_columns(db: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table})")
    return {str(row[1]) for row in await cursor.fetchall()}


async def test_every_sqlite_table_is_modelled(sqlite_db: aiosqlite.Connection) -> None:
    assert await sqlite_tables(sqlite_db) == set(metadata.tables)


async def test_no_table_gained_or_lost_a_column(sqlite_db: aiosqlite.Connection) -> None:
    differences: dict[str, dict[str, list[str]]] = {}
    for table_name in sorted(await sqlite_tables(sqlite_db)):
        source = await sqlite_columns(sqlite_db, table_name)
        target = {column.name for column in metadata.tables[table_name].columns}
        if source != target:
            differences[table_name] = {
                "only_in_sqlite": sorted(source - target),
                "only_in_postgres": sorted(target - source),
            }

    assert differences == {}


async def test_primary_keys_match(sqlite_db: aiosqlite.Connection) -> None:
    """A different primary key changes the row ordering the checksums rely on."""
    differences: dict[str, dict[str, list[str]]] = {}
    for table_name in sorted(await sqlite_tables(sqlite_db)):
        cursor = await sqlite_db.execute(f"PRAGMA table_info({table_name})")
        rows = await cursor.fetchall()
        source = sorted(str(row[1]) for row in rows if int(row[5]) > 0)
        target = sorted(column.name for column in metadata.tables[table_name].primary_key.columns)
        if source != target:
            differences[table_name] = {"sqlite": source, "postgres": target}

    assert differences == {}


async def test_not_null_columns_match(sqlite_db: aiosqlite.Connection) -> None:
    """A column that loses NOT NULL accepts the nulls a checksum would then hide.

    Primary keys are excluded on both sides: SQLite's ``table_info`` reports
    ``notnull = 0`` for them even though it enforces non-nullability anyway, so
    comparing them here would flag every table. ``test_primary_keys_match``
    covers those instead.
    """
    differences: dict[str, dict[str, list[str]]] = {}
    for table_name in sorted(await sqlite_tables(sqlite_db)):
        table = metadata.tables[table_name]
        primary_key = {column.name for column in table.primary_key.columns}
        cursor = await sqlite_db.execute(f"PRAGMA table_info({table_name})")
        rows = await cursor.fetchall()
        source = sorted(
            str(row[1]) for row in rows if int(row[3]) == 1 and str(row[1]) not in primary_key
        )
        target = sorted(
            column.name
            for column in table.columns
            if not column.nullable and column.name not in primary_key
        )
        if source != target:
            differences[table_name] = {"sqlite": source, "postgres": target}

    assert differences == {}


async def test_parity_check_would_notice_a_dropped_column(
    sqlite_db: aiosqlite.Connection,
) -> None:
    """Guards the guard: prove the comparison is not vacuously true."""
    await sqlite_db.execute("ALTER TABLE study_sessions ADD COLUMN untracked TEXT")

    source = await sqlite_columns(sqlite_db, "study_sessions")
    target = {column.name for column in metadata.tables["study_sessions"].columns}

    assert source - target == {"untracked"}
