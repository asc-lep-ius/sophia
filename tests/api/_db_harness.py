"""Harness for API tests that need a real database behind the routes.

Routes open their own session through the container, so fixture rows have to be
committed before a request runs — a test cannot seed inside a transaction it
holds open and expect the route to see it. ``seed`` exists for exactly that.

The client is an in-loop ``httpx.AsyncClient`` rather than ``TestClient``: the
latter drives the app on its own event loop while the engine's asyncpg
connections belong to the test's, and crossing the two closes connections out
from under the pool.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

import httpx

from sophia.api import create_api_app
from sophia.api.routers.auth import LoginIdentity
from sophia.api.sessions import (
    RedisSessionStore,
    SecretKeySessionManager,
    SessionCore,
    SessionCredential,
    SessionSettings,
    SessionTenant,
    SessionUser,
)
from sophia.config import Settings
from sophia.infra.engine import create_session_factory, session_scope

from ._session_helpers import VALID_SESSION_KEY, FakeRedis

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    from sophia.api.schemas.auth import AuthLoginRequest
    from sophia.infra.di import AppContainer

TEST_ORG_ID = "tu-wien"


@dataclass(frozen=True)
class DbContainer:
    """The slice of AppContainer that database-backed routes actually use.

    ``settings`` is here because question generation reads the Hermes config
    from it to record which model produced a question.
    """

    session_factory: async_sessionmaker[AsyncSession]
    settings: Settings = field(default_factory=Settings)

    def session(self, *, org_id: str | None = None):
        return session_scope(self.session_factory, org_id=org_id)


@dataclass(frozen=True, slots=True)
class DbHarness:
    client: httpx.AsyncClient
    settings: Settings
    container: DbContainer

    @contextlib.asynccontextmanager
    async def seed(self) -> AsyncIterator[AsyncSession]:
        """Open a committing session for fixture rows a later request must see."""
        async with self.container.session(org_id=TEST_ORG_ID) as session:
            yield session

    async def login(self, username: str = "learner") -> None:
        response = await self.client.post(
            "/api/auth/login",
            json={"username": username, "password": "correct horse battery staple"},
        )
        assert response.status_code == 200, response.text

    def csrf_headers(self) -> dict[str, str]:
        token = self.client.cookies.get(self.settings.csrf_cookie_name)
        assert token is not None
        return {"X-Requested-With": "fetch", "X-CSRF-Token": token}


def learning_path_tenant(learning_path_id: int = 12) -> SessionTenant:
    return SessionTenant(
        org_id=TEST_ORG_ID,
        learning_path_id=str(learning_path_id),
        cohort_id="cohort-a",
        role="student",
    )


@contextlib.asynccontextmanager
async def db_harness(
    engine: AsyncEngine,
    *,
    tenant: SessionTenant | None = None,
) -> AsyncIterator[DbHarness]:
    """Serve the API against a real engine, with a logged-in-capable client."""
    settings = Settings(session_ttl_seconds=600)
    core = SessionCore(
        store=RedisSessionStore(redis=FakeRedis(), ttl_seconds=settings.session_ttl_seconds),
        signer=SecretKeySessionManager(current_key=VALID_SESSION_KEY),
    )
    container = DbContainer(
        session_factory=create_session_factory(engine),
        settings=settings,
    )
    app = create_api_app(
        settings=settings,
        session_core=core,
        login_authenticator=_login_as(tenant or learning_path_tenant()),
        app_container=cast("AppContainer", container),
    )

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        yield DbHarness(client=client, settings=settings, container=container)


def _login_as(tenant: SessionTenant):
    async def authenticate(payload: AuthLoginRequest, _settings: Settings) -> LoginIdentity:
        return LoginIdentity(
            user=SessionUser(
                id=payload.username,
                display_name="Learner One",
                email=f"{payload.username}@example.test",
            ),
            tenant=tenant,
            settings=SessionSettings(
                theme="system",
                locale="en",
                selected_learning_path_id=tenant.learning_path_id,
            ),
            tuwel_credentials=SessionCredential(
                reference="tuwel:test-session",
                payload={"username": payload.username},
            ),
        )

    return authenticate
