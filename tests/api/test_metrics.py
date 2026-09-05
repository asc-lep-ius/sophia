"""API metrics endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from sophia.api import create_api_app

FORBIDDEN_PROMETHEUS_LABELS = {
    "user_id",
    "learner_id",
    "email",
    "session_id",
    "raw_route_params",
    "question_id",
    "card_id",
    "prompt",
    "content",
    "content_text",
}


def test_metrics_returns_prometheus_text() -> None:
    response = TestClient(create_api_app()).get("/api/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# HELP" in response.text


def test_metrics_exposes_default_http_metrics() -> None:
    client = TestClient(create_api_app())

    assert client.get("/api/health").status_code == 200

    response = client.get("/api/metrics")

    metric_names = {family.name for family in text_string_to_metric_families(response.text)}

    assert "http_requests" in metric_names
    assert "http_request_duration_seconds" in metric_names


def test_metrics_exposes_low_cardinality_custom_metrics() -> None:
    response = TestClient(create_api_app()).get("/api/metrics")
    metric_names = {family.name for family in text_string_to_metric_families(response.text)}

    assert {
        "sse_connections_open",
        "sse_events_emitted",
        "sse_disconnect",
        "web_vitals_reports",
    } <= metric_names


def test_prometheus_metrics_do_not_use_forbidden_labels() -> None:
    response = TestClient(create_api_app()).get("/api/metrics")

    label_names = {
        label_name
        for family in text_string_to_metric_families(response.text)
        for sample in family.samples
        for label_name in sample.labels
    }

    assert label_names.isdisjoint(FORBIDDEN_PROMETHEUS_LABELS)


def test_web_vitals_report_is_counted() -> None:
    client = TestClient(create_api_app())

    response = client.post(
        "/api/metrics/web-vitals",
        json={
            "metric_name": "INP",
            "rating": "needs_improvement",
            "value": 187.5,
            "navigation_type": "navigate",
        },
    )
    scrape = client.get("/api/metrics")

    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "code": "metrics.web_vitals.accepted",
    }
    assert (
        'web_vitals_reports_total{metric_name="INP",rating="needs_improvement"} 1.0' in scrape.text
    )


def test_web_vitals_rejects_a_metric_name_outside_the_closed_set() -> None:
    """An open label would let a client mint unbounded Prometheus series."""
    response = TestClient(create_api_app()).post(
        "/api/metrics/web-vitals",
        json={"metric_name": "MADE_UP", "rating": "good", "value": 1.0},
    )

    assert response.status_code == 422
