"""Shared fake session infrastructure for API tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from sophia.api import create_api_app
from sophia.api.routers.auth import LoginIdentity
from sophia.api.sessions import (
    RedisSessionStore,
    SecretKeySessionManager,
    SessionCore,
    SessionCredential,
    SessionSettings,
    SessionStoreBackend,
    SessionTenant,
    SessionUser,
)
from sophia.config import Settings

if TYPE_CHECKING:
    from fastapi import FastAPI

    from sophia.api.routers.auth import LoginAuthenticator
    from sophia.api.schemas.auth import AuthLoginRequest
    from sophia.infra.di import AppContainer

VALID_SESSION_KEY = "api-test-session-signing-key-32-bytes"


class FakeRedis:
    """Small async Redis fake with enough TTL behavior for API tests."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expires_at: dict[str, int] = {}
        self.now = 0

    async def set(
        self,
        name: str,
        value: str,
        ex: int | None = None,
        *,
        xx: bool = False,
        keepttl: bool = False,
    ) -> bool:
        self._purge(name)
        if xx and name not in self.values:
            return False

        current_expiry = self.expires_at.get(name)
        self.values[name] = value
        if keepttl:
            if current_expiry is not None:
                self.expires_at[name] = current_expiry
            else:
                self.expires_at.pop(name, None)
        elif ex is None:
            self.expires_at.pop(name, None)
        else:
            self.expires_at[name] = self.now + ex
        return True

    async def get(self, name: str) -> str | None:
        self._purge(name)
        return self.values.get(name)

    async def delete(self, *names: str) -> int:
        deleted_count = 0
        for name in names:
            self._purge(name)
            if name in self.values:
                deleted_count += 1
                self.values.pop(name)
                self.expires_at.pop(name, None)
        return deleted_count

    async def expire(self, name: str, time: int) -> bool:
        self._purge(name)
        if name not in self.values:
            return False
        self.expires_at[name] = self.now + time
        return True

    async def ttl(self, name: str) -> int:
        self._purge(name)
        if name not in self.values:
            return -2
        expires_at = self.expires_at.get(name)
        if expires_at is None:
            return -1
        return max(expires_at - self.now, 0)

    def advance(self, seconds: int) -> None:
        self.now += seconds
        for name in tuple(self.values):
            self._purge(name)

    def _purge(self, name: str) -> None:
        expires_at = self.expires_at.get(name)
        if expires_at is not None and expires_at <= self.now:
            self.values.pop(name, None)
            self.expires_at.pop(name, None)


@dataclass(frozen=True, slots=True)
class ApiHarness:
    app: FastAPI
    client: TestClient
    redis: FakeRedis
    core: SessionCore
    settings: Settings


def build_harness(
    login_authenticator: LoginAuthenticator | None = None,
    *,
    store: SessionStoreBackend | None = None,
    redis: FakeRedis | None = None,
    app_container: AppContainer | None = None,
    tenant: SessionTenant | None = None,
) -> ApiHarness:
    settings = Settings(session_ttl_seconds=600)
    redis = redis or FakeRedis()
    core = SessionCore(
        store=store or RedisSessionStore(redis=redis, ttl_seconds=settings.session_ttl_seconds),
        signer=SecretKeySessionManager(current_key=VALID_SESSION_KEY),
    )
    app = create_api_app(
        settings=settings,
        session_core=core,
        login_authenticator=login_authenticator or _successful_login_for_tenant(tenant),
        app_container=app_container,
    )
    client = TestClient(app, base_url="https://testserver")
    return ApiHarness(app=app, client=client, redis=redis, core=core, settings=settings)


async def successful_login(payload: AuthLoginRequest, _settings: Settings) -> LoginIdentity:
    return _login_identity(payload, tenant=None)


def _successful_login_for_tenant(tenant: SessionTenant | None) -> LoginAuthenticator:
    async def authenticate(payload: AuthLoginRequest, _settings: Settings) -> LoginIdentity:
        return _login_identity(payload, tenant=tenant)

    return authenticate


def _login_identity(payload: AuthLoginRequest, tenant: SessionTenant | None) -> LoginIdentity:
    session_tenant = tenant or SessionTenant(
        org_id="tu-wien",
        learning_path_id="course-1",
        cohort_id="cohort-a",
        role="student",
    )
    return LoginIdentity(
        user=SessionUser(
            id=payload.username,
            display_name="Learner One",
            email=f"{payload.username}@example.test",
        ),
        tenant=session_tenant,
        settings=SessionSettings(
            theme="system",
            locale="en",
            selected_learning_path_id=session_tenant.learning_path_id,
        ),
        tuwel_credentials=SessionCredential(
            reference="tuwel:test-session",
            payload={"username": payload.username},
        ),
    )


def login(harness: ApiHarness, username: str = "learner") -> None:
    response = harness.client.post(
        "/api/auth/login",
        json={"username": username, "password": "correct horse battery staple"},
    )
    assert response.status_code == 200, response.text


def csrf_headers(harness: ApiHarness) -> dict[str, str]:
    csrf_cookie = harness.client.cookies.get(harness.settings.csrf_cookie_name)
    assert csrf_cookie is not None
    return {"X-Requested-With": "fetch", "X-CSRF-Token": csrf_cookie}
