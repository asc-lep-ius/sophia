"""SQLite connection factory and schema migrations."""

from __future__ import annotations

from pathlib import Path

import aiosqlite
import structlog

log = structlog.get_logger()


async def connect_db(path: Path) -> aiosqlite.Connection:
    """Open SQLite with production-safe pragmas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(path)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")
    await db.execute("PRAGMA synchronous=NORMAL")
    return db


async def run_migrations(db: aiosqlite.Connection) -> None:
    """Apply numbered SQL migration files idempotently.

    Uses BEGIN EXCLUSIVE to prevent race conditions when two processes
    start concurrently.
    """
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await db.commit()

    await db.execute("BEGIN EXCLUSIVE")
    try:
        cursor = await db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
        row = await cursor.fetchone()
        current_version: int = row[0] if row else 0

        migrations_dir = Path(__file__).parent / "migrations"
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
                        "INSERT INTO schema_version (version) VALUES (?)", (version,)
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
