"""Composition root — wires all dependencies with proper lifecycle management."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
import structlog

from sophia.adapters.auth import (
    KeyringUnavailableError,
    SessionCredentials,
    load_session,
    session_path,
)
from sophia.adapters.lecture_downloader import HttpLectureDownloader
from sophia.adapters.lecturetube import OpencastAdapter
from sophia.adapters.moodle import MoodleAdapter
from sophia.adapters.tiss import TissAdapter
from sophia.config import Settings
from sophia.domain.errors import AuthError
from sophia.infra.alembic_runner import upgrade_async
from sophia.infra.engine import create_engine, create_session_factory, session_scope
from sophia.infra.http import http_session
from sophia.services.upstream_session import (
    UpstreamSession,
    UpstreamStatus,
    reauthenticate,
    tuwel_session_alive,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

log = structlog.get_logger()

_DI_INIT_TIMEOUT_S = 30
# A re-login may first wait out a spent TOTP step (up to 31 s), then run the
# whole SSO flow for TUWEL and TISS.
_UPSTREAM_CHECK_TIMEOUT_S = 90


@dataclass(frozen=True)
class AppContainer:
    """Wired application dependencies. Created once at startup, passed to services.

    The container holds the session *factory*, never a session. An
    ``AsyncSession`` is not safe to use from two coroutines at once, and the GUI
    and job runner both run concurrent tasks, so every unit of work opens its
    own through :meth:`session`.
    """

    settings: Settings
    http: httpx.AsyncClient
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    moodle: MoodleAdapter
    tiss: TissAdapter
    opencast: OpencastAdapter
    lecture_downloader: HttpLectureDownloader
    upstream: UpstreamSession = field(default_factory=UpstreamSession)

    def session(self, *, org_id: str | None = None) -> AbstractAsyncContextManager[AsyncSession]:
        """Open one transaction-scoped session bound to an org.

        Commits on clean exit, rolls back on exception. ``org_id`` defaults to
        the ambient scope, which nothing sets yet — see
        :mod:`sophia.infra.org_context`.
        """
        return session_scope(self.session_factory, org_id=org_id)


@contextlib.asynccontextmanager
async def create_app(settings: Settings | None = None):
    """Async context manager that builds and tears down the dependency graph.

    Uses AsyncExitStack to keep the composition root flat and extensible.
    Each new phase adds one line instead of another nesting level.
    """
    if settings is None:
        settings = Settings()

    upstream = await _startup_session(settings, load_session(session_path(settings.config_dir)))
    if upstream.creds is None:
        why = f" ({upstream.status.reason})" if upstream.status.reason else ""
        raise AuthError(f"Not logged in — run: sophia auth login{why}")

    async with contextlib.AsyncExitStack() as stack:
        try:
            container = await asyncio.wait_for(
                _init_resources(stack, settings, upstream),
                timeout=_DI_INIT_TIMEOUT_S,
            )
        except TimeoutError:
            msg = (
                f"Application startup timed out after {_DI_INIT_TIMEOUT_S}s"
                " — check database and network"
            )
            raise RuntimeError(msg) from None

        yield container


async def _startup_session(
    settings: Settings, stored: SessionCredentials | None
) -> UpstreamSession:
    """Validate the stored TUWEL session, and log in again if it has died.

    The file only proves somebody logged in once; after a night with the
    machine off the session behind it is gone (TUWEL: 8 h idle). Starting on
    it anyway is how every TUWEL page turned into a 401 after a successful
    web login (#125). When it cannot be renewed the process still starts on
    what it has, with the session reported as expired, so pages that need no
    TUWEL keep working and readiness says why the rest do not.
    """
    try:
        async with asyncio.timeout(_UPSTREAM_CHECK_TIMEOUT_S):
            if stored is not None and await tuwel_session_alive(stored, settings.tuwel_host):
                return UpstreamSession(stored, UpstreamStatus("valid"))
            log.info("upstream_session.renewing_at_startup", had_stored_login=stored is not None)
            renewed = await reauthenticate(
                settings.config_dir, settings.tuwel_host, settings.tiss_host, stale=stored
            )
    # OSError: a config dir the process cannot write (#111's container case).
    # ValueError: a stored secret that is not base32. Both are a broken setup
    # to report, not a reason to refuse to start.
    except (AuthError, KeyringUnavailableError, OSError, ValueError) as exc:
        log.error("upstream_session.startup_renewal_failed", reason=str(exc))
        return UpstreamSession(stored, UpstreamStatus("expired", str(exc)))
    except (httpx.HTTPError, TimeoutError) as exc:
        log.warning("upstream_session.unreachable_at_startup", error=type(exc).__name__)
        return UpstreamSession(stored, UpstreamStatus("unreachable", type(exc).__name__))
    return UpstreamSession(renewed, UpstreamStatus("valid"))


async def _init_resources(
    stack: contextlib.AsyncExitStack,
    settings: Settings,
    upstream: UpstreamSession,
) -> AppContainer:
    """Initialize all resources — extracted so create_app can wrap with a timeout."""
    creds = upstream.creds
    if creds is None:
        raise AuthError("Not logged in — run: sophia auth login")
    http = await stack.enter_async_context(http_session())
    tuwel_domain = urlparse(settings.tuwel_host).hostname or ""
    http.cookies.set(creds.cookie_name, creds.moodle_session, domain=tuwel_domain)
    engine = create_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout,
        pool_recycle=settings.database_pool_recycle,
        echo=settings.database_echo,
    )
    stack.push_async_callback(engine.dispose)
    await upgrade_async(settings.database_url)
    session_factory = create_session_factory(engine)

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
        engine=engine,
        session_factory=session_factory,
        moodle=moodle,
        tiss=tiss,
        opencast=opencast,
        lecture_downloader=lecture_downloader,
        upstream=upstream,
    )
