"""API liveness endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sophia.api import create_api_app


def test_api_health_returns_ok() -> None:
    client = TestClient(create_api_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
