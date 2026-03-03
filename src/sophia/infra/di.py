"""Composition root — wires all dependencies with proper lifecycle management."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sophia.adapters.moodle import MoodleAdapter
from sophia.config import Settings

if TYPE_CHECKING:
    import aiosqlite
    import httpx
from sophia.infra.http import http_session
from sophia.infra.persistence import connect_db, run_migrations


@dataclass(frozen=True)
class AppContainer:
    """Wired application dependencies. Created once at startup, passed to services."""

    settings: Settings
    http: httpx.AsyncClient
    db: aiosqlite.Connection
    moodle: MoodleAdapter


@contextlib.asynccontextmanager
async def create_app(settings: Settings | None = None):
    """Async context manager that builds and tears down the dependency graph.

    Uses AsyncExitStack to keep the composition root flat and extensible.
    Each new phase adds one line instead of another nesting level.
    """
    if settings is None:
        settings = Settings()

    async with contextlib.AsyncExitStack() as stack:
        http = await stack.enter_async_context(http_session())
        db = await connect_db(settings.db_path)
        stack.push_async_callback(db.close)
        await run_migrations(db)

        moodle = MoodleAdapter(
            http=http,
            token=settings.tuwel_token,
            host=settings.tuwel_host,
        )

        yield AppContainer(
            settings=settings,
            http=http,
            db=db,
            moodle=moodle,
        )
