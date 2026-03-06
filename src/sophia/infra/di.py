"""Composition root — wires all dependencies with proper lifecycle management."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from sophia.adapters.auth import load_session, session_path
from sophia.adapters.moodle import MoodleAdapter
from sophia.adapters.tiss import TissAdapter
from sophia.config import Settings
from sophia.domain.errors import AuthError

if TYPE_CHECKING:
    import aiosqlite
    import httpx
from sophia.infra.http import http_session
from sophia.infra.persistence import connect_db, run_migrations

log = structlog.get_logger()


@dataclass(frozen=True)
class AppContainer:
    """Wired application dependencies. Created once at startup, passed to services."""

    settings: Settings
    http: httpx.AsyncClient
    db: aiosqlite.Connection
    moodle: MoodleAdapter
    tiss: TissAdapter


@contextlib.asynccontextmanager
async def create_app(settings: Settings | None = None):
    """Async context manager that builds and tears down the dependency graph.

    Uses AsyncExitStack to keep the composition root flat and extensible.
    Each new phase adds one line instead of another nesting level.
    """
    if settings is None:
        settings = Settings()

    creds = load_session(session_path(settings.config_dir))
    if creds is None:
        raise AuthError("Not logged in — run: sophia auth login")

    async with contextlib.AsyncExitStack() as stack:
        http = await stack.enter_async_context(http_session())
        db = await connect_db(settings.db_path)
        stack.push_async_callback(db.close)
        await run_migrations(db)

        moodle = MoodleAdapter(
            http=http,
            sesskey=creds.sesskey,
            moodle_session=creds.moodle_session,
            host=settings.tuwel_host,
            cookie_name=creds.cookie_name,
        )

        tiss = TissAdapter(http=http, host=settings.tiss_host)

        yield AppContainer(
            settings=settings,
            http=http,
            db=db,
            moodle=moodle,
            tiss=tiss,
        )
