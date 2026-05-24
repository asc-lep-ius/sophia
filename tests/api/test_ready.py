"""API readiness endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sophia.api import create_api_app


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
