"""NiceGUI read-only auth bridge tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from sophia.api.sessions import (
    RedisSessionStore,
    SecretKeySessionManager,
    SessionCore,
    SessionCredential,
    SessionRecord,
    SessionSettings,
    SessionTenant,
    SessionUser,
)
from sophia.config import Settings
from sophia.gui.auth_bridge import AuthBridgeMiddleware, get_auth_bridge_state

from ._session_helpers import VALID_SESSION_KEY, FakeRedis

if TYPE_CHECKING:
    from httpx import Response
    from starlette.requests import Request


@dataclass(frozen=True, slots=True)
class BridgeHarness:
    client: TestClient
    redis: RecordingRedis
    settings: Settings
    store: RedisSessionStore
    core: SessionCore


class RecordingRedis(FakeRedis):
    """Fake Redis that records mutating operations after test setup."""

    def __init__(self) -> None:
        super().__init__()
        self.set_calls = 0
        self.expire_calls = 0
        self.delete_calls = 0

    async def set(
        self,
        name: str,
        value: str,
        ex: int | None = None,
        *,
        xx: bool = False,
        keepttl: bool = False,
    ) -> bool:
        self.set_calls += 1
        return await super().set(name, value, ex, xx=xx, keepttl=keepttl)

    async def expire(self, name: str, time: int) -> bool:
        self.expire_calls += 1
        return await super().expire(name, time)

    async def delete(self, *names: str) -> int:
        self.delete_calls += 1
        return await super().delete(*names)

    def reset_mutation_counts(self) -> None:
        self.set_calls = 0
        self.expire_calls = 0
        self.delete_calls = 0


async def test_bridge_resolves_valid_api_session_cookie() -> None:
    harness = _build_harness()
    record = _session_record(session_id="bridge-session")
    cookie = await harness.core.create(record)

    response = _get_legacy_with_cookie(harness, cookie)

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "session_id": "bridge-session",
        "user_id": "learner-1",
        "display_name": "Learner One",
        "org_id": "tu-wien",
        "course_id": "course-1",
        "role": "student",
        "tuwel": None,
        "tiss": None,
    }


async def test_bridge_returns_anonymous_state_without_cookie() -> None:
    response = _build_harness().client.get("/legacy")

    assert response.status_code == 200
    assert response.json() == _anonymous_payload()


async def test_bridge_returns_anonymous_state_when_session_is_missing() -> None:
    harness = _build_harness()
    missing_cookie = harness.core.signer.sign({"session_id": "deleted-session"})

    response = _get_legacy_with_cookie(harness, missing_cookie)

    assert response.status_code == 200
    assert response.json() == _anonymous_payload()


async def test_bridge_returns_anonymous_state_when_session_is_expired() -> None:
    harness = _build_harness()
    cookie = await harness.core.create(_session_record(session_id="expired-session"))
    harness.redis.advance(harness.settings.session_ttl_seconds + 1)

    response = _get_legacy_with_cookie(harness, cookie)

    assert response.status_code == 200
    assert response.json() == _anonymous_payload()


async def test_bridge_returns_anonymous_state_for_invalid_signed_cookie() -> None:
    harness = _build_harness()

    response = _get_legacy_with_cookie(harness, "tampered-cookie")

    assert response.status_code == 200
    assert response.json() == _anonymous_payload()
    assert harness.redis.set_calls == 0
    assert harness.redis.expire_calls == 0
    assert harness.redis.delete_calls == 0


async def test_bridge_exposes_credential_payloads_without_refreshing_ttl() -> None:
    harness = _build_harness()
    record = _session_record(
        session_id="credential-session",
        tuwel_credentials=SessionCredential(
            reference="secret:tuwel",
            payload={"username": "learner", "sesskey": "abc123"},
        ),
        tiss_credentials=SessionCredential(
            payload={"jsessionid": "jsid", "cookies": {"TISS": "token"}},
        ),
    )
    cookie = await harness.core.create(record)
    harness.redis.advance(37)
    ttl_before = await harness.store.ttl(record.session_id)
    harness.redis.reset_mutation_counts()

    response = _get_legacy_with_cookie(harness, cookie)

    assert response.status_code == 200
    assert response.json()["tuwel"] == {"username": "learner", "sesskey": "abc123"}
    assert response.json()["tiss"] == {"jsessionid": "jsid", "cookies": {"TISS": "token"}}
    assert await harness.store.ttl(record.session_id) == ttl_before
    assert harness.redis.set_calls == 0
    assert harness.redis.expire_calls == 0
    assert harness.redis.delete_calls == 0


def _build_harness() -> BridgeHarness:
    settings = Settings(session_ttl_seconds=600)
    redis = RecordingRedis()
    store = RedisSessionStore(redis=redis, ttl_seconds=settings.session_ttl_seconds)
    core = SessionCore(
        store=store,
        signer=SecretKeySessionManager(current_key=VALID_SESSION_KEY),
    )
    starlette_app = Starlette(routes=[Route("/legacy", _bridge_payload)])
    starlette_app.add_middleware(
        AuthBridgeMiddleware,
        settings=settings,
        session_core=core,
    )
    redis.reset_mutation_counts()
    return BridgeHarness(
        client=TestClient(starlette_app, base_url="https://testserver"),
        redis=redis,
        settings=settings,
        store=store,
        core=core,
    )


def _get_legacy_with_cookie(harness: BridgeHarness, cookie_value: str) -> Response:
    harness.client.cookies.set(harness.settings.session_cookie_name, cookie_value)
    return harness.client.get("/legacy")


async def _bridge_payload(request: Request) -> JSONResponse:
    bridge = get_auth_bridge_state(request)
    return JSONResponse(
        {
            "authenticated": bridge.authenticated,
            "session_id": bridge.session_id,
            "user_id": bridge.user.id if bridge.user else None,
            "display_name": bridge.user.display_name if bridge.user else None,
            "org_id": bridge.tenant.org_id if bridge.tenant else None,
            "course_id": bridge.tenant.course_id if bridge.tenant else None,
            "role": bridge.tenant.role if bridge.tenant else None,
            "tuwel": bridge.tuwel_credential_payload,
            "tiss": bridge.tiss_credential_payload,
        }
    )


def _session_record(
    *,
    session_id: str,
    tuwel_credentials: SessionCredential | None = None,
    tiss_credentials: SessionCredential | None = None,
) -> SessionRecord:
    return SessionRecord(
        session_id=session_id,
        user=SessionUser(id="learner-1", display_name="Learner One"),
        csrf_token="csrf-token",
        tenant=SessionTenant(
            org_id="tu-wien",
            course_id="course-1",
            cohort_id="cohort-a",
            role="student",
        ),
        settings=SessionSettings(theme="system", locale="en", selected_course_id="course-1"),
        tuwel_credentials=tuwel_credentials,
        tiss_credentials=tiss_credentials,
        created_at="2026-05-25T00:00:00Z",
        updated_at="2026-05-25T00:00:00Z",
    )


def _anonymous_payload() -> dict[str, object]:
    return {
        "authenticated": False,
        "session_id": None,
        "user_id": None,
        "display_name": None,
        "org_id": None,
        "course_id": None,
        "role": None,
        "tuwel": None,
        "tiss": None,
    }
