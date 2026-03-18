"""Composition root — wires all dependencies with proper lifecycle management."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import structlog

from sophia.adapters.auth import SessionCredentials, load_session, session_path
from sophia.adapters.lecture_downloader import HttpLectureDownloader
from sophia.adapters.lecturetube import OpencastAdapter
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

_DI_INIT_TIMEOUT_S = 30


@dataclass(frozen=True)
class AppContainer:
    """Wired application dependencies. Created once at startup, passed to services."""

    settings: Settings
    http: httpx.AsyncClient
    db: aiosqlite.Connection
    moodle: MoodleAdapter
    tiss: TissAdapter
    opencast: OpencastAdapter
    lecture_downloader: HttpLectureDownloader


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
        try:
            container = await asyncio.wait_for(
                _init_resources(stack, settings, creds),
                timeout=_DI_INIT_TIMEOUT_S,
            )
        except TimeoutError:
            msg = (
                f"Application startup timed out after {_DI_INIT_TIMEOUT_S}s"
                " \u2014 check database and network"
            )
            raise RuntimeError(msg) from None

        yield container


async def _init_resources(
    stack: contextlib.AsyncExitStack,
    settings: Settings,
    creds: SessionCredentials,
) -> AppContainer:
    """Initialize all resources — extracted so create_app can wrap with a timeout."""
    http = await stack.enter_async_context(http_session())
    tuwel_domain = urlparse(settings.tuwel_host).hostname or ""
    http.cookies.set(creds.cookie_name, creds.moodle_session, domain=tuwel_domain)
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
    opencast = OpencastAdapter(http=http, host=settings.tuwel_host)
    lecture_downloader = HttpLectureDownloader(http=http)

    return AppContainer(
        settings=settings,
        http=http,
        db=db,
        moodle=moodle,
        tiss=tiss,
        opencast=opencast,
        lecture_downloader=lecture_downloader,
    )
