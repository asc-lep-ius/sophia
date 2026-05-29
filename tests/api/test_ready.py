"""API readiness endpoint tests."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from fastapi.testclient import TestClient

from sophia.api import app as api_app_module
from sophia.api import create_api_app, create_standalone_api_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    import pytest

    from sophia.config import Settings
    from sophia.infra.di import AppContainer


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: object


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
