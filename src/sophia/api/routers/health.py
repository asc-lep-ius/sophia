"""Health and readiness routes for the backend API."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, status
from starlette.responses import JSONResponse, StreamingResponse

from sophia.api.schemas.health import HealthResponse, ReadinessCheck, ReadinessResponse

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def ready(request: Request) -> ReadinessResponse | JSONResponse:
    checks = _readiness_checks(request)
    is_ready = all(check.ok for check in checks)
    response = ReadinessResponse(status="ready" if is_ready else "not_ready", checks=checks)
    if is_ready:
        return response
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=response.model_dump()
    )


@router.get("/events", include_in_schema=False)
async def events(request: Request) -> StreamingResponse:
    return StreamingResponse(
        _operational_event_stream(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _readiness_checks(request: Request) -> list[ReadinessCheck]:
    return [
        ReadinessCheck(name="database", ok=bool(getattr(request.app.state, "db_ready", False))),
        ReadinessCheck(
            name="sse_broker",
            ok=bool(getattr(request.app.state, "sse_broker_ready", False)),
        ),
    ]


async def _operational_event_stream(request: Request) -> AsyncIterator[str]:
    checks = _readiness_checks(request)
    status_value = "ready" if all(check.ok for check in checks) else "not_ready"
    payload = json.dumps({"status": status_value}, separators=(",", ":"))
    yield f"event: ready\ndata: {payload}\n\n"
