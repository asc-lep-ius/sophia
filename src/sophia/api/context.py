"""Per-request API context backed by ContextVar."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from starlette.datastructures import Headers, MutableHeaders

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send


REQUEST_ID_SCOPE_KEY = "sophia.request_id"


@dataclass(frozen=True, slots=True)
class RequestContext:
    """API request-local context."""

    request_id: str
    org_id: str = "local"
    learning_path_id: str = "default-learning-path"
    cohort_id: str = "default-cohort"
    user_id: str = "anonymous"
    role: str = "student"


_request_context: ContextVar[RequestContext | None] = ContextVar(
    "sophia_request_context",
    default=None,
)


def get_request_context() -> RequestContext | None:
    """Return the current request context, if one is active."""
    return _request_context.get()


def require_request_context() -> RequestContext:
    """Return the active request context or raise when called outside a request."""
    context = get_request_context()
    if context is None:
        msg = "request context is not active"
        raise RuntimeError(msg)
    return context


class RequestContextMiddleware:
    """ASGI middleware that sets and clears request context for HTTP requests."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = _extract_request_id(scope)
        scope[REQUEST_ID_SCOPE_KEY] = request_id
        token = _request_context.set(RequestContext(request_id=request_id))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            await self._app(scope, receive, self._send_with_request_id(send, request_id))
        finally:
            structlog.contextvars.clear_contextvars()
            _request_context.reset(token)

    def _send_with_request_id(self, send: Send, request_id: str) -> Send:
        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)

        return send_with_request_id


def _extract_request_id(scope: Scope) -> str:
    header_value = Headers(scope=scope).get("x-request-id", "").strip()
    return header_value or uuid.uuid4().hex


def get_scope_request_id(scope: Scope) -> str | None:
    request_id = scope.get(REQUEST_ID_SCOPE_KEY)
    if isinstance(request_id, str) and request_id:
        return request_id
    return None
