"""Tests for SQLite connection factory and schema migrations."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sophia.infra.persistence import connect_db, run_migrations

if TYPE_CHECKING:
    from pathlib import Path


class TestConnectDb:
    @pytest.mark.asyncio
    async def test_creates_directory_and_connects(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nested" / "dir" / "sophia.db"
        db = await connect_db(db_path)
        try:
            assert db_path.parent.exists()
            # WAL mode pragma should be active
            cursor = await db.execute("PRAGMA journal_mode")
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "wal"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_foreign_keys_enabled(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sophia.db"
        db = await connect_db(db_path)
        try:
            cursor = await db.execute("PRAGMA foreign_keys")
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == 1
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_migrations_run_on_fresh_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sophia.db"
        db = await connect_db(db_path)
        try:
            await run_migrations(db)
            # After migrations, schema_version table should exist
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            row = await cursor.fetchone()
            assert row is not None
        finally:
            await db.close()
