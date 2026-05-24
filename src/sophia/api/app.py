"""FastAPI application factory for the backend API seam."""

from __future__ import annotations

from fastapi import FastAPI

from sophia import __version__
from sophia.api.context import RequestContextMiddleware
from sophia.api.errors import register_error_handlers
from sophia.api.routers import health, metrics
from sophia.config import Settings


def create_api_app(settings: Settings | None = None, *, route_prefix: str = "/api") -> FastAPI:
    """Create the backend API app.

    ``route_prefix`` defaults to ``/api`` for standalone testing. The GUI mounts
    the same app at ``/api`` with an empty prefix during the transient phase.
    """
    resolved_settings = settings or Settings()
    resolved_settings.validate_secret_key_configuration()

    api_app = FastAPI(title="Sophia API", version=__version__)
    api_app.state.settings = resolved_settings
    api_app.state.db_ready = False
    api_app.state.sse_broker_ready = False

    api_app.add_middleware(RequestContextMiddleware)
    register_error_handlers(api_app)
    api_app.include_router(health.router, prefix=_normalize_route_prefix(route_prefix))
    api_app.include_router(metrics.router, prefix=_normalize_route_prefix(route_prefix))
    return api_app


def _normalize_route_prefix(route_prefix: str) -> str:
    if route_prefix == "/":
        return ""
    return route_prefix.rstrip("/")
