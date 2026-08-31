"""Harness for exercising API routes against a real database.

Uses an in-loop ``httpx.AsyncClient`` rather than ``TestClient``: the latter
drives the app on its own event loop, while the engine's asyncpg connections
belong to the test's loop, and crossing the two closes connections out from
under the pool.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, cast

import httpx

from sophia.api import create_api_app
from sophia.api.sessions import RedisSessionStore, SecretKeySessionManager, SessionCore
from sophia.config import Settings

from ..api._session_helpers import VALID_SESSION_KEY, FakeRedis

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from fastapi import APIRouter

    from sophia.infra.di import AppContainer


@contextlib.asynccontextmanager
async def db_client(container: object, router: APIRouter) -> AsyncIterator[httpx.AsyncClient]:
    """Serve the API app, plus a probe router, against a real container."""
    settings = Settings(session_ttl_seconds=600)
    core = SessionCore(
        store=RedisSessionStore(redis=FakeRedis(), ttl_seconds=settings.session_ttl_seconds),
        signer=SecretKeySessionManager(current_key=VALID_SESSION_KEY),
    )
    app = create_api_app(
        settings=settings,
        session_core=core,
        app_container=cast("AppContainer", container),
    )
    app.include_router(router, prefix="/api")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        yield client
