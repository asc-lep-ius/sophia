"""FastAPI application factory for the backend API seam."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from sophia import __version__
from sophia.api.context import RequestContextMiddleware
from sophia.api.errors import register_error_handlers
from sophia.api.routers import health, metrics
from sophia.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def create_api_app(
    settings: Settings | None = None,
    *,
    route_prefix: str = "/api",
    ready_on_startup: bool = False,
) -> FastAPI:
    """Create the backend API app.

    ``route_prefix`` defaults to ``/api`` for standalone testing. The GUI mounts
    the same app at ``/api`` with an empty prefix during the transient phase.
    """
    resolved_settings = settings or Settings()
    resolved_settings.validate_secret_key_configuration()

    api_app = FastAPI(
        title="Sophia API",
        version=__version__,
        lifespan=_standalone_api_lifespan if ready_on_startup else None,
    )
    api_app.state.settings = resolved_settings
    _set_runtime_readiness(api_app, ready=False)

    api_app.add_middleware(RequestContextMiddleware)
    register_error_handlers(api_app)
    api_app.include_router(health.router, prefix=_normalize_route_prefix(route_prefix))
    api_app.include_router(metrics.router, prefix=_normalize_route_prefix(route_prefix))
    return api_app


def create_standalone_api_app(settings: Settings | None = None) -> FastAPI:
    """Create the Uvicorn-served API app used by standalone API containers."""
    return create_api_app(settings, ready_on_startup=True)


def _normalize_route_prefix(route_prefix: str) -> str:
    if route_prefix == "/":
        return ""
    return route_prefix.rstrip("/")


@asynccontextmanager
async def _standalone_api_lifespan(api_app: FastAPI) -> AsyncIterator[None]:
    _set_runtime_readiness(api_app, ready=True)
    try:
        yield
    finally:
        _set_runtime_readiness(api_app, ready=False)


def _set_runtime_readiness(api_app: FastAPI, *, ready: bool) -> None:
    api_app.state.db_ready = ready
    api_app.state.sse_broker_ready = ready
