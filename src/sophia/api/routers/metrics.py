"""Metrics routes for the backend API."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from sophia.api.schemas.metrics import WebVitalsReservedResponse

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.post(
    "/metrics/web-vitals",
    response_model=WebVitalsReservedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reserve_web_vitals() -> WebVitalsReservedResponse:
    return WebVitalsReservedResponse(status="reserved", code="metrics.web_vitals.reserved")
