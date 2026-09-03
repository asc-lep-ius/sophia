"""Async Postgres engine, session factory, and the org-context transaction hook.

Every transaction opened through :func:`session_scope` issues
``set_config('app.org_id', ..., true)`` before any statement runs. The ``true``
makes it ``SET LOCAL`` semantics: the setting is scoped to the transaction and
Postgres discards it at commit or rollback, so a pooled connection handed to the
next request never carries the previous tenant's scope.

``set_config`` is used rather than literal ``SET LOCAL app.org_id = ...``
because a bare ``SET`` cannot be parameterised, and interpolating a tenant
identifier into DDL-ish SQL is exactly the injection this hook exists to make
unnecessary.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, cast

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sophia.infra.org_context import get_org_id

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy import CursorResult, Result
    from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger()

ORG_SETTING = "app.org_id"
_SET_ORG_SQL = text("SELECT set_config(:setting, :org_id, true)")
_PING_SQL = text("SELECT 1")


def asyncpg_dsn(database_url: str) -> str:
    """Convert the SQLAlchemy ``postgresql+asyncpg://`` URL to a plain asyncpg DSN.

    ``asyncpg.connect`` speaks the bare ``postgresql://`` scheme; the driver
    suffix is a SQLAlchemy-ism it does not understand.
    """
    return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def create_engine(
    database_url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 1800,
    echo: bool = False,
) -> AsyncEngine:
    """Build the async engine.

    ``pool_pre_ping`` is on because a connection recycled by Postgres or by a
    proxy in between requests should fail on checkout, not halfway through a
    learner's transaction.
    """
    return create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,
        echo=echo,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build the session factory.

    ``expire_on_commit`` is off so that values read before a commit stay usable
    after it; with it on, every attribute access after commit is another
    round-trip, which in async code is an await in a surprising place.
    """
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@contextlib.asynccontextmanager
async def session_scope(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    org_id: str | None = None,
) -> AsyncIterator[AsyncSession]:
    """Open one transaction-scoped session bound to an org.

    One session per request or per task — never shared across concurrent tasks,
    because an ``AsyncSession`` is not safe to use from two coroutines at once.
    """
    resolved_org_id = org_id if org_id is not None else get_org_id()
    async with session_factory() as session, session.begin():
        await apply_org_context(session, resolved_org_id)
        yield session


async def apply_org_context(session: AsyncSession, org_id: str) -> None:
    """Bind the org scope to the session's current transaction."""
    if not session.in_transaction():
        msg = "org context requires an active transaction — SET LOCAL is transaction-scoped"
        raise RuntimeError(msg)
    await session.execute(_SET_ORG_SQL, {"setting": ORG_SETTING, "org_id": org_id})


async def current_org_setting(session: AsyncSession) -> str:
    """Read back the org scope Postgres currently has for this transaction."""
    result = await session.execute(
        text("SELECT current_setting(:setting, true)"),
        {"setting": ORG_SETTING},
    )
    return result.scalar_one_or_none() or ""


def affected_rows(result: Result[Any]) -> int:
    """Rows a DML statement touched.

    ``AsyncSession.execute`` is typed as returning ``Result``, which has no
    ``rowcount``; for DML it is a ``CursorResult`` at runtime.
    """
    return max(cast("CursorResult[Any]", result).rowcount, 0)


async def check_connection(engine: AsyncEngine) -> bool:
    """Return whether Postgres answers, for readiness reporting."""
    try:
        async with engine.connect() as connection:
            await connection.execute(_PING_SQL)
    except Exception as exc:  # noqa: BLE001 — readiness must report, never raise
        log.warning("postgres_unavailable", error=str(exc))
        return False
    return True
