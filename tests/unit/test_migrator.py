"""Tests for migration runner and status reporting."""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiosqlite
import pytest

from sophia.infra.persistence import get_migration_status, run_migrations

if TYPE_CHECKING:
    from pathlib import Path


def _write_migration(dir: Path, name: str, sql: str) -> None:
    from pathlib import Path as _Path

    _Path(str(dir)).mkdir(parents=True, exist_ok=True)
    (_Path(str(dir)) / name).write_text(sql)


class TestRunMigrations:
    @pytest.mark.asyncio
    async def test_fresh_db_applies_all_migrations(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "migrations"
        _write_migration(mig_dir, "001_init.sql", "CREATE TABLE t1 (id INTEGER PRIMARY KEY)")
        _write_migration(mig_dir, "002_add.sql", "CREATE TABLE t2 (id INTEGER PRIMARY KEY)")

        async with aiosqlite.connect(":memory:") as db:
            await run_migrations(db, migrations_dir=mig_dir)

            cursor = await db.execute(
                "SELECT version, filename FROM schema_version ORDER BY version"
            )
            rows = list(await cursor.fetchall())
            assert len(rows) == 2
            assert rows[0] == (1, "001_init.sql")
            assert rows[1] == (2, "002_add.sql")

    @pytest.mark.asyncio
    async def test_existing_db_skips_applied(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "migrations"
        _write_migration(mig_dir, "001_init.sql", "CREATE TABLE t1 (id INTEGER PRIMARY KEY)")
        _write_migration(mig_dir, "002_add.sql", "CREATE TABLE t2 (id INTEGER PRIMARY KEY)")

        async with aiosqlite.connect(":memory:") as db:
            # Apply first migration only
            await run_migrations(db, migrations_dir=mig_dir)

            # Add a third migration
            _write_migration(mig_dir, "003_more.sql", "CREATE TABLE t3 (id INTEGER PRIMARY KEY)")
            await run_migrations(db, migrations_dir=mig_dir)

            cursor = await db.execute("SELECT COUNT(*) FROM schema_version")
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == 3

            # Verify t3 was actually created
            cursor = await db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='t3'"
            )
            assert await cursor.fetchone() is not None

    @pytest.mark.asyncio
    async def test_failed_migration_rolls_back(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "migrations"
        _write_migration(mig_dir, "001_init.sql", "CREATE TABLE t1 (id INTEGER PRIMARY KEY)")
        _write_migration(mig_dir, "002_bad.sql", "INVALID SQL STATEMENT")

        async with aiosqlite.connect(":memory:") as db:
            with pytest.raises(Exception):  # noqa: B017
                await run_migrations(db, migrations_dir=mig_dir)

            # Only version 0 should be recorded (nothing applied)
            cursor = await db.execute("SELECT COUNT(*) FROM schema_version")
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == 0

    @pytest.mark.asyncio
    async def test_schema_version_has_filename_column(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "migrations"
        _write_migration(mig_dir, "001_init.sql", "CREATE TABLE t1 (id INTEGER PRIMARY KEY)")

        async with aiosqlite.connect(":memory:") as db:
            await run_migrations(db, migrations_dir=mig_dir)

            cursor = await db.execute("PRAGMA table_info(schema_version)")
            columns = {row[1] for row in await cursor.fetchall()}
            assert "filename" in columns


class TestGetMigrationStatus:
    @pytest.mark.asyncio
    async def test_returns_correct_info(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "migrations"
        _write_migration(mig_dir, "001_init.sql", "CREATE TABLE t1 (id INTEGER PRIMARY KEY)")
        _write_migration(mig_dir, "002_add.sql", "CREATE TABLE t2 (id INTEGER PRIMARY KEY)")
        _write_migration(mig_dir, "003_more.sql", "CREATE TABLE t3 (id INTEGER PRIMARY KEY)")

        async with aiosqlite.connect(":memory:") as db:
            # Apply only first two
            (mig_dir / "003_more.sql").unlink()
            await run_migrations(db, migrations_dir=mig_dir)

            # Restore third so status sees it as pending
            _write_migration(mig_dir, "003_more.sql", "CREATE TABLE t3 (id INTEGER PRIMARY KEY)")

            status = await get_migration_status(db, migrations_dir=mig_dir)
            assert status["current_version"] == 2
            assert len(status["applied"]) == 2
            assert len(status["pending"]) == 1
            assert status["pending"][0]["version"] == 3
            assert status["pending"][0]["filename"] == "003_more.sql"

    @pytest.mark.asyncio
    async def test_status_on_fresh_db(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "migrations"
        _write_migration(mig_dir, "001_init.sql", "CREATE TABLE t1 (id INTEGER PRIMARY KEY)")

        async with aiosqlite.connect(":memory:") as db:
            await run_migrations(db, migrations_dir=mig_dir)

            # Remove all migration files — nothing pending
            (mig_dir / "001_init.sql").unlink()

            status = await get_migration_status(db, migrations_dir=mig_dir)
            assert status["current_version"] == 1
            assert len(status["applied"]) == 1
            assert len(status["pending"]) == 0
