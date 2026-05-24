"""Health and readiness routes for the backend API."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from starlette.responses import JSONResponse

from sophia.api.schemas.health import HealthResponse, ReadinessCheck, ReadinessResponse

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


def _readiness_checks(request: Request) -> list[ReadinessCheck]:
    return [
        ReadinessCheck(name="database", ok=bool(getattr(request.app.state, "db_ready", False))),
        ReadinessCheck(
            name="sse_broker",
            ok=bool(getattr(request.app.state, "sse_broker_ready", False)),
        ),
    ]
