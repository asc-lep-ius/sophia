"""API readiness endpoint tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, cast

from fastapi.testclient import TestClient

from sophia.api import app as api_app_module
from sophia.api import create_api_app, create_standalone_api_app

from ._session_helpers import FakeAppContainer

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import pytest

    from sophia.config import Settings
    from sophia.infra.di import AppContainer


def test_api_ready_requires_database_and_sse_broker() -> None:
    api_app = create_api_app()
    client = TestClient(api_app)

    not_ready_response = client.get("/api/ready")
    assert not_ready_response.status_code == 503
    assert not_ready_response.json() == {
        "status": "not_ready",
        "checks": [
            {"name": "database", "ok": False},
            {"name": "sse_broker", "ok": False},
        ],
    }

    api_app.state.db_ready = True
    partially_ready_response = client.get("/api/ready")
    assert partially_ready_response.status_code == 503
    assert partially_ready_response.json()["status"] == "not_ready"

    api_app.state.sse_broker_ready = True
    ready_response = client.get("/api/ready")
    assert ready_response.status_code == 200
    assert ready_response.json() == {
        "status": "ready",
        "checks": [
            {"name": "database", "ok": True},
            {"name": "sse_broker", "ok": True},
        ],
    }


def test_standalone_api_marks_ready_during_lifespan(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_container = cast("AppContainer", FakeAppContainer(db=object()))

    @asynccontextmanager
    async def fake_create_app_container(
        _settings: Settings | None = None,
    ) -> AsyncIterator[AppContainer]:
        yield fake_container

    monkeypatch.setattr(api_app_module, "create_app_container", fake_create_app_container)
    api_app = create_standalone_api_app()
    pre_startup_response = TestClient(api_app).get("/api/ready")
    assert pre_startup_response.status_code == 503

    with TestClient(api_app) as client:
        ready_response = client.get("/api/ready")

    assert ready_response.status_code == 200
    assert ready_response.json() == {
        "status": "ready",
        "checks": [
            {"name": "database", "ok": True},
            {"name": "sse_broker", "ok": True},
        ],
    }
    assert api_app.state.db_ready is False
    assert api_app.state.sse_broker_ready is False


def test_standalone_api_stores_container_for_domain_routers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_container = cast("AppContainer", FakeAppContainer(db=object()))

    @asynccontextmanager
    async def fake_create_app_container(
        _settings: Settings | None = None,
    ) -> AsyncIterator[AppContainer]:
        yield fake_container

    monkeypatch.setattr(api_app_module, "create_app_container", fake_create_app_container)
    api_app = create_standalone_api_app()

    with TestClient(api_app):
        assert api_app.state.app_container is fake_container


def test_ready_reports_503_when_postgres_stops_answering() -> None:
    """Readiness must track the database now, not only at startup.

    A flag set once during lifespan keeps the container reporting healthy long
    after Postgres has gone away, which is exactly when orchestration needs to
    take it out of rotation.
    """

    class DeadEngine:
        def connect(self) -> object:
            msg = "connection refused"
            raise OSError(msg)

    api_app = create_api_app(ready_on_startup=True)
    api_app.state.app_container = cast(
        "AppContainer", FakeAppContainer(db=object(), engine=DeadEngine())
    )
    # Start from the state a completed lifespan leaves behind — Postgres
    # answered at boot. Without this the startup flag is still False and the
    # 503 would come from the flag, never reaching the probe under test.
    api_app.state.db_ready = True
    api_app.state.sse_broker_ready = True

    response = TestClient(api_app).get("/api/ready")

    assert response.status_code == 503
    checks = {check["name"]: check["ok"] for check in response.json()["checks"]}
    assert checks["database"] is False


def test_an_expired_tu_wien_session_degrades_readiness_without_failing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Decided on #124: pages that need no TUWEL keep working, so the API stays ready."""
    from sophia.services.upstream_session import UpstreamSession, UpstreamStatus

    upstream = UpstreamSession(None, UpstreamStatus("expired", "No TOTP secret stored"))
    fake_container = cast("AppContainer", FakeAppContainer(db=object(), upstream=upstream))

    @asynccontextmanager
    async def fake_create_app_container(
        _settings: Settings | None = None,
    ) -> AsyncIterator[AppContainer]:
        yield fake_container

    monkeypatch.setattr(api_app_module, "create_app_container", fake_create_app_container)
    with TestClient(create_standalone_api_app()) as client:
        response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": [
            {"name": "database", "ok": True},
            {"name": "sse_broker", "ok": True},
            # The state only: the reason names the setup gap, and this route is public.
            {"name": "upstream_session", "ok": False, "required": False, "detail": "expired"},
        ],
    }


def test_the_api_lifespan_runs_the_keepalive_and_stops_it_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario 3 needs the keepalive running inside the API, not merely defined."""
    import asyncio

    started: list[float] = []
    cancelled = asyncio.Event()

    class RecordingKeepalive:
        def __init__(self, container: object) -> None:
            self.container = container

        async def run(self, interval_s: float) -> None:
            started.append(interval_s)
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    fake_container = cast("AppContainer", FakeAppContainer(db=object()))

    @asynccontextmanager
    async def fake_create_app_container(
        _settings: Settings | None = None,
    ) -> AsyncIterator[AppContainer]:
        yield fake_container

    monkeypatch.setattr(api_app_module, "create_app_container", fake_create_app_container)
    monkeypatch.setattr(api_app_module, "SessionKeepalive", RecordingKeepalive)
    monkeypatch.setenv("SOPHIA_SESSION_KEEPALIVE_INTERVAL", "120")

    with TestClient(create_standalone_api_app()) as client:
        assert client.get("/api/ready").status_code == 200
        assert started == [120]

    assert cancelled.is_set()
