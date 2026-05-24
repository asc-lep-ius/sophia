"""API metrics endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

from sophia.api import create_api_app


def test_metrics_returns_prometheus_text() -> None:
    response = TestClient(create_api_app()).get("/api/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# HELP" in response.text


def test_web_vitals_endpoint_is_reserved_placeholder() -> None:
    response = TestClient(create_api_app()).post("/api/metrics/web-vitals", json={})

    assert response.status_code == 202
    assert response.json() == {
        "status": "reserved",
        "code": "metrics.web_vitals.reserved",
    }
