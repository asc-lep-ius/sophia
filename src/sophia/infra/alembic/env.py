"""Alembic environment — async engine, metadata-driven autogenerate.

Lives inside the package rather than at the repository root because only
``src/`` is copied into the runtime image, and migrations have to run there.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

from sophia.config import Settings
from sophia.infra.schema import metadata

if TYPE_CHECKING:
    from sqlalchemy.engine import Connection

config = context.config
target_metadata = metadata


def _database_url() -> str:
    """Resolve the target database.

    A URL set on the config wins, so callers driving Alembic programmatically
    stay in control. Otherwise fall back to application settings, which keeps
    the connection string out of a checked-in ini file.
    """
    url = config.get_main_option("sqlalchemy.url", None)
    if url:
        return url
    return Settings().database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting, for review of a pending upgrade."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Apply migrations over an async connection."""
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    engine = async_engine_from_config(section, prefix="sqlalchemy.", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
