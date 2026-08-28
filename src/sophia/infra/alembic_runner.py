"""Programmatic Alembic entry points.

The container has no repository checkout and therefore no ``alembic.ini`` at a
known relative path, so the config is built from the package directory instead
of being read from disk. Alembic's own API is synchronous; each entry point runs
it in a worker thread so an async caller never blocks the event loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from anyio import to_thread
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger()

ALEMBIC_DIR = Path(__file__).parent / "alembic"

_CURRENT_REVISION_SQL = text(
    "SELECT version_num FROM alembic_version "
    "WHERE to_regclass('public.alembic_version') IS NOT NULL"
)


def build_config(database_url: str) -> Config:
    """Build an Alembic config bound to one database URL."""
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def upgrade(database_url: str, revision: str = "head") -> None:
    """Apply migrations up to ``revision``."""
    command.upgrade(build_config(database_url), revision)
    log.info("alembic_upgraded", revision=revision)


def downgrade(database_url: str, revision: str) -> None:
    """Roll migrations back to ``revision``."""
    command.downgrade(build_config(database_url), revision)
    log.info("alembic_downgraded", revision=revision)


def head_revision(database_url: str) -> str | None:
    """Return the newest revision the migration scripts define."""
    return ScriptDirectory.from_config(build_config(database_url)).get_current_head()


async def current_revision(engine: AsyncEngine) -> str | None:
    """Return the revision the database is stamped at, or None if unstamped.

    Reads ``alembic_version`` over the async engine rather than through
    Alembic's own synchronous MigrationContext, so no second, blocking driver
    has to be installed just to answer a readiness question.
    """
    async with engine.connect() as connection:
        result = await connection.execute(_CURRENT_REVISION_SQL)
        return result.scalar_one_or_none()


async def upgrade_async(database_url: str, revision: str = "head") -> None:
    """Apply migrations without blocking the caller's event loop.

    Alembic's ``env.py`` opens its own event loop, so it has to run on a worker
    thread rather than on the caller's.
    """
    await to_thread.run_sync(upgrade, database_url, revision)


async def is_up_to_date(engine: AsyncEngine, database_url: str) -> bool:
    """Return whether the database is stamped at the newest revision."""
    return await current_revision(engine) == head_revision(database_url)
