"""Health and readiness endpoints for the GUI server."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request

log = structlog.get_logger()

# Module-level container reference — set by app.py during startup
_container_ref: dict[str, Any] = {"container": None, "error": None}


def get_container() -> Any:
    """Return the DI container, or None if not initialized."""
    return _container_ref["container"]


def set_container(container: object) -> None:
    """Mark the DI container as initialized."""
    _container_ref["container"] = container
    _container_ref["error"] = None


def set_container_error(error: str) -> None:
    """Record a startup error (e.g. AuthError)."""
    _container_ref["container"] = None
    _container_ref["error"] = error


def reset_state() -> None:
    """Reset health state — used in tests."""
    _container_ref["container"] = None
    _container_ref["error"] = None


async def health(_request: Request) -> JSONResponse:
    """Liveness probe — always returns 200 if the server is running."""
    return JSONResponse({"status": "ok"})


async def ready(_request: Request) -> JSONResponse:
    """Readiness probe — 200 when AppContainer is initialized, 503 otherwise."""
    if _container_ref["error"]:
        log.warning("ready_check_failed", error=_container_ref["error"])
        return JSONResponse(
            {"status": "not_ready", "error": _container_ref["error"]},
            status_code=503,
        )
    if _container_ref["container"] is None:
        return JSONResponse(
            {"status": "not_ready", "error": "container not initialized"},
            status_code=503,
        )
    return JSONResponse({"status": "ready"})
