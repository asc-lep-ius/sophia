"""Health and readiness routes for the backend API."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, Request, status
from starlette.responses import JSONResponse, StreamingResponse

from sophia.api.schemas.health import HealthResponse, ReadinessCheck, ReadinessResponse
from sophia.api.transactions import TransactionalRoute
from sophia.infra.engine import check_connection

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sophia.services.upstream_session import UpstreamSession

router = APIRouter(tags=["health"], route_class=TransactionalRoute)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    # The gating checks keep their two-field shape; only a check that is not
    # required, or carries a detail, says so.
    response_model_exclude_defaults=True,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def ready(request: Request) -> ReadinessResponse | JSONResponse:
    checks = await _readiness_checks(request)
    is_ready = all(check.ok for check in checks if check.required)
    response = ReadinessResponse(status="ready" if is_ready else "not_ready", checks=checks)
    if is_ready:
        return response
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=response.model_dump(exclude_defaults=True),
    )


@router.get("/events", include_in_schema=False)
async def events(request: Request) -> StreamingResponse:
    return StreamingResponse(
        _operational_event_stream(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _readiness_checks(request: Request) -> list[ReadinessCheck]:
    checks = [
        ReadinessCheck(name="database", ok=await _database_ready(request)),
        ReadinessCheck(
            name="sse_broker",
            ok=bool(getattr(request.app.state, "sse_broker_ready", False)),
        ),
    ]
    upstream = _upstream_session_check(request)
    if upstream is not None:
        checks.append(upstream)
    return checks


def _upstream_session_check(request: Request) -> ReadinessCheck | None:
    """Whether the stack can reach TU Wien as the learner — degraded, never unready.

    Not required, by decision on #124: with the session expired the API still
    serves everything that needs no TUWEL, and a proof walk then fails at
    sign-in with the real cause instead of "the stack never came up". The
    reason stays in the log; this unauthenticated route says only the state.
    """
    container = getattr(request.app.state, "app_container", None)
    upstream = cast("UpstreamSession | None", getattr(container, "upstream", None))
    if upstream is None:
        return None
    state = upstream.status.state
    return ReadinessCheck(
        name="upstream_session", ok=state == "valid", required=False, detail=state
    )


async def _database_ready(request: Request) -> bool:
    """Ask Postgres, rather than trusting a flag set once at startup.

    A startup-only flag keeps reporting ready after the database goes away,
    which is the opposite of what the container healthcheck needs. The probe is
    a ``SELECT 1`` on a pooled connection, so it is not worth caching — a cached
    answer would reintroduce the lag this exists to remove.
    """
    if not getattr(request.app.state, "db_ready", False):
        return False
    container = getattr(request.app.state, "app_container", None)
    engine = getattr(container, "engine", None)
    if engine is None:
        return True
    return await check_connection(engine)


async def _operational_event_stream(request: Request) -> AsyncIterator[str]:
    checks = await _readiness_checks(request)
    status_value = "ready" if all(check.ok for check in checks if check.required) else "not_ready"
    payload = json.dumps({"status": status_value}, separators=(",", ":"))
    yield f"event: ready\ndata: {payload}\n\n"
