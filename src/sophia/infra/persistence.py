"""SQLite connection factory and schema migrations."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import aiosqlite
import structlog

log = structlog.get_logger()


class _AppliedMigration(TypedDict):
    version: int
    filename: str
    applied_at: str


class _PendingMigration(TypedDict):
    version: int
    filename: str


class MigrationStatus(TypedDict):
    current_version: int
    applied: list[_AppliedMigration]
    pending: list[_PendingMigration]


async def connect_db(path: Path) -> aiosqlite.Connection:
    """Open SQLite with production-safe pragmas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(path)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA synchronous=NORMAL")
    return db


_DEFAULT_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def run_migrations(
    db: aiosqlite.Connection,
    *,
    migrations_dir: Path | None = None,
) -> None:
    """Apply numbered SQL migrations idempotently (BEGIN EXCLUSIVE for safety)."""
    migrations_dir = migrations_dir or _DEFAULT_MIGRATIONS_DIR
    await db.execute("""CREATE TABLE IF NOT EXISTS schema_version (
        version    INTEGER PRIMARY KEY,
        filename   TEXT NOT NULL,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    await db.commit()

    await db.execute("BEGIN EXCLUSIVE")
    try:
        cursor = await db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        row = await cursor.fetchone()
        current_version: int = row[0] if row else 0

        if not migrations_dir.exists():
            await db.commit()
            return

        for sql_file in sorted(migrations_dir.glob("*.sql")):
            version = int(sql_file.stem.split("_")[0])
            if version > current_version:
                sql = sql_file.read_text()
                try:
                    for statement in sql.split(";"):
                        statement = statement.strip()
                        if statement:
                            await db.execute(statement)
                    await db.execute(
                        "INSERT INTO schema_version (version, filename) VALUES (?, ?)",
                        (version, sql_file.name),
                    )
                    log.info("migration_applied", version=version, file=sql_file.name)
                except Exception:
                    log.error(
                        "migration_failed",
                        version=version,
                        file=sql_file.name,
                        sql=sql[:500],
                    )
                    raise
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def get_migration_status(
    db: aiosqlite.Connection,
    *,
    migrations_dir: Path | None = None,
) -> MigrationStatus:
    """Return current version, applied migrations, and pending files."""
    migrations_dir = migrations_dir or _DEFAULT_MIGRATIONS_DIR

    cursor = await db.execute(
        "SELECT version, filename, applied_at FROM schema_version ORDER BY version"
    )
    applied: list[_AppliedMigration] = [
        _AppliedMigration(version=r[0], filename=r[1], applied_at=r[2])
        for r in await cursor.fetchall()
    ]
    current_version = applied[-1]["version"] if applied else 0

    pending: list[_PendingMigration] = []
    if migrations_dir.exists():
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            version = int(sql_file.stem.split("_")[0])
            if version > current_version:
                pending.append(_PendingMigration(version=version, filename=sql_file.name))

    return MigrationStatus(current_version=current_version, applied=applied, pending=pending)
