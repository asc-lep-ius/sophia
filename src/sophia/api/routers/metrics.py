"""Metrics routes for the backend API."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

from sophia.api.schemas.metrics import (
    WebVitalsAcceptedResponse,
    WebVitalsMetricName,
    WebVitalsRating,
    WebVitalsReportRequest,
)
from sophia.api.transactions import TransactionalRoute

router = APIRouter(tags=["metrics"], route_class=TransactionalRoute)

SSE_CONNECTIONS_OPEN = Gauge(
    "sse_connections_open",
    "Open server-sent event connections by stream type.",
    ("stream",),
)
SSE_EVENTS_EMITTED = Counter(
    "sse_events_emitted",
    "Server-sent events emitted by stream and event type.",
    ("stream", "event_type"),
)
SSE_DISCONNECTS = Counter(
    "sse_disconnect",
    "Server-sent event disconnects by stream and coarse reason.",
    ("stream", "reason"),
)
WEB_VITALS_REPORTS = Counter(
    "web_vitals_reports",
    "Web-vitals reports accepted by metric name and rating bucket.",
    ("metric_name", "rating"),
)


def _initialize_custom_metric_series() -> None:
    SSE_CONNECTIONS_OPEN.labels(stream="study").set(0)
    SSE_EVENTS_EMITTED.labels(stream="study", event_type="heartbeat").inc(0)
    SSE_DISCONNECTS.labels(stream="study", reason="client").inc(0)
    for metric_name in WebVitalsMetricName:
        for rating in WebVitalsRating:
            WEB_VITALS_REPORTS.labels(metric_name=metric_name.value, rating=rating.value).inc(0)


_initialize_custom_metric_series()


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.post(
    "/metrics/web-vitals",
    response_model=WebVitalsAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="reportWebVitals",
)
async def report_web_vitals(payload: WebVitalsReportRequest) -> WebVitalsAcceptedResponse:
    """Count one field measurement of the study surface's responsiveness.

    Unauthenticated on purpose — responsiveness is measured on the sign-in page
    too — and safe to leave so because the only effect is incrementing a
    counter whose labels come from a closed set.
    """
    WEB_VITALS_REPORTS.labels(
        metric_name=payload.metric_name.value,
        rating=payload.rating.value,
    ).inc()
    return WebVitalsAcceptedResponse(status="accepted", code="metrics.web_vitals.accepted")
