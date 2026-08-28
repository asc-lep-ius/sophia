"""Operational SSE endpoint tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from fastapi.testclient import TestClient

from sophia.api import create_api_app, create_standalone_api_app

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer


@dataclass(frozen=True, slots=True)
class FakeAppContainer:
    db: object


def test_api_events_emits_ready_sse_smoke_event() -> None:
    fake_container = cast("AppContainer", FakeAppContainer(db=object()))
    api_app = create_standalone_api_app(app_container=fake_container)

    with (
        TestClient(api_app) as client,
        client.stream(
            "GET",
            "/api/events",
            headers={"accept": "text/event-stream"},
        ) as response,
    ):
        body = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    assert body == 'event: ready\ndata: {"status":"ready"}\n\n'


def test_api_events_reports_not_ready_before_lifespan_startup() -> None:
    api_app = create_api_app()
    client = TestClient(api_app)

    response = client.get("/api/events", headers={"accept": "text/event-stream"})

    assert response.status_code == 200
    assert response.text == 'event: ready\ndata: {"status":"not_ready"}\n\n'
