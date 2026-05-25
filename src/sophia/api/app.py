"""FastAPI application factory for the backend API seam."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import sentry_sdk
from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from sophia import __version__
from sophia.api.context import RequestContextMiddleware
from sophia.api.errors import register_error_handlers
from sophia.api.routers import health, metrics
from sophia.config import Settings
from sophia.infra.logging import (
    REDACTED_VALUE,
    is_sensitive_observability_key,
    setup_logging,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sentry_sdk.types import Event, Hint


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
    _setup_observability(resolved_settings)

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
    _instrument_prometheus(api_app)
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


def _setup_observability(settings: Settings) -> None:
    setup_logging(
        debug=settings.log_debug,
        json_logs=settings.log_format == "json",
        service_name="api",
    )
    _initialize_sentry(settings)


def _initialize_sentry(settings: Settings) -> None:
    dsn = settings.sentry_dsn.strip()
    if not dsn:
        return

    sentry_sdk.init(
        dsn=dsn,
        release=settings.sentry_release or None,
        environment=settings.sentry_environment,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        include_local_variables=False,
        before_send=_scrub_sentry_event,
    )


def _scrub_sentry_event(event: Event, _hint: Hint) -> Event | None:
    scrubbed_event = cast("dict[str, Any]", event)
    request = scrubbed_event.get("request")
    if isinstance(request, dict):
        _scrub_sentry_request(cast("dict[str, Any]", request))

    _drop_sentry_exception_frame_vars(scrubbed_event)
    _scrub_sentry_breadcrumbs(scrubbed_event)

    for top_level_key in ("extra", "contexts", "tags", "user"):
        value = scrubbed_event.get(top_level_key)
        if isinstance(value, dict):
            scrubbed_event[top_level_key] = _scrub_sensitive_mapping(cast("dict[str, Any]", value))
    return cast("Event", scrubbed_event)


def _scrub_sentry_request(request: dict[str, Any]) -> None:
    headers = request.get("headers")
    if isinstance(headers, dict):
        request["headers"] = _scrub_headers(cast("dict[str, Any]", headers))

    for sensitive_key in ("cookies", "query_string", "data", "env"):
        request.pop(sensitive_key, None)


def _drop_sentry_exception_frame_vars(event: dict[str, Any]) -> None:
    exception = event.get("exception")
    if not isinstance(exception, dict):
        return

    exception_mapping = cast("dict[str, Any]", exception)
    values = exception_mapping.get("values")
    if not isinstance(values, list):
        return

    for value in cast("list[Any]", values):
        if not isinstance(value, dict):
            continue
        value_mapping = cast("dict[str, Any]", value)
        stacktrace = value_mapping.get("stacktrace")
        if not isinstance(stacktrace, dict):
            continue
        stacktrace_mapping = cast("dict[str, Any]", stacktrace)
        frames = stacktrace_mapping.get("frames")
        if not isinstance(frames, list):
            continue
        for frame in cast("list[Any]", frames):
            if isinstance(frame, dict):
                frame_mapping = cast("dict[str, Any]", frame)
                frame_mapping.pop("vars", None)


def _scrub_sentry_breadcrumbs(event: dict[str, Any]) -> None:
    breadcrumbs = event.get("breadcrumbs")
    if not isinstance(breadcrumbs, dict):
        return

    breadcrumbs_mapping = cast("dict[str, Any]", breadcrumbs)
    values = breadcrumbs_mapping.get("values")
    if not isinstance(values, list):
        return

    for breadcrumb in cast("list[Any]", values):
        if isinstance(breadcrumb, dict):
            _scrub_sentry_breadcrumb(cast("dict[str, Any]", breadcrumb))


def _scrub_sentry_breadcrumb(breadcrumb: dict[str, Any]) -> None:
    data = breadcrumb.get("data")
    if isinstance(data, dict):
        breadcrumb["data"] = _scrub_sensitive_mapping(cast("dict[str, Any]", data))
    elif isinstance(data, list):
        breadcrumb["data"] = [
            _scrub_sensitive_sequence_item(item) for item in cast("list[Any]", data)
        ]

    message = breadcrumb.get("message")
    if isinstance(message, dict):
        breadcrumb["message"] = _scrub_sensitive_mapping(cast("dict[str, Any]", message))
    elif isinstance(message, list):
        breadcrumb["message"] = [
            _scrub_sensitive_sequence_item(item) for item in cast("list[Any]", message)
        ]
    elif isinstance(message, str) and is_sensitive_observability_key(message):
        breadcrumb["message"] = REDACTED_VALUE


def _scrub_headers(headers: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): REDACTED_VALUE if is_sensitive_observability_key(key) else value
        for key, value in headers.items()
    }


def _scrub_sensitive_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    scrubbed: dict[str, Any] = {}
    for key, value in mapping.items():
        normalized_key = str(key)
        if is_sensitive_observability_key(normalized_key):
            scrubbed[normalized_key] = REDACTED_VALUE
        elif isinstance(value, dict):
            scrubbed[normalized_key] = _scrub_sensitive_mapping(cast("dict[str, Any]", value))
        elif isinstance(value, list):
            items = cast("list[Any]", value)
            scrubbed[normalized_key] = [_scrub_sensitive_sequence_item(item) for item in items]
        else:
            scrubbed[normalized_key] = value
    return scrubbed


def _scrub_sensitive_sequence_item(item: Any) -> Any:
    if isinstance(item, dict):
        return _scrub_sensitive_mapping(cast("dict[str, Any]", item))
    if isinstance(item, list):
        children = cast("list[Any]", item)
        return [_scrub_sensitive_sequence_item(child) for child in children]
    return item


def _instrument_prometheus(api_app: FastAPI) -> None:
    Instrumentator(excluded_handlers=["/api/metrics", "/metrics"]).instrument(api_app)
