"""Read-only bridge from API session cookies into legacy NiceGUI requests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from redis import asyncio as redis_asyncio
from starlette.middleware import Middleware
from starlette.requests import Request

from sophia.api.sessions import (
    InvalidSessionToken,
    JsonObject,
    RedisSessionBackend,
    SessionCore,
    SessionCredential,
    SessionRecord,
    SessionSettings,
    SessionTenant,
    SessionUser,
    create_session_core,
)

if TYPE_CHECKING:
    from starlette.applications import Starlette
    from starlette.types import ASGIApp, Receive, Scope, Send

    from sophia.config import Settings

AUTH_BRIDGE_STATE_ATTR = "sophia_auth_bridge"
AUTH_BRIDGE_SESSION_CORE_STATE_ATTR = "sophia_auth_bridge_session_core"
AUTH_BRIDGE_SETTINGS_STATE_ATTR = "sophia_auth_bridge_settings"


@dataclass(frozen=True, slots=True)
class NiceGUIAuthBridgeState:
    """Request-local authenticated identity resolved from the API session store."""

    record: SessionRecord | None = None

    @property
    def authenticated(self) -> bool:
        return self.record is not None

    @property
    def session_id(self) -> str | None:
        if self.record is None:
            return None
        return self.record.session_id

    @property
    def user(self) -> SessionUser | None:
        if self.record is None:
            return None
        return self.record.user

    @property
    def tenant(self) -> SessionTenant | None:
        if self.record is None:
            return None
        return self.record.tenant

    @property
    def settings(self) -> SessionSettings | None:
        if self.record is None:
            return None
        return self.record.settings

    @property
    def tuwel_credentials(self) -> SessionCredential | None:
        if self.record is None:
            return None
        return self.record.tuwel_credentials

    @property
    def tiss_credentials(self) -> SessionCredential | None:
        if self.record is None:
            return None
        return self.record.tiss_credentials

    @property
    def tuwel_credential_payload(self) -> JsonObject | None:
        return _copy_credential_payload(self.tuwel_credentials)

    @property
    def tiss_credential_payload(self) -> JsonObject | None:
        return _copy_credential_payload(self.tiss_credentials)


ANONYMOUS_AUTH_BRIDGE_STATE = NiceGUIAuthBridgeState()


class AuthBridgeMiddleware:
    """Resolve the signed API session cookie into request state without refreshing TTL."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: Settings,
        session_core: SessionCore,
    ) -> None:
        self.app = app
        self.settings = settings
        self.session_core = session_core

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            request = Request(scope, receive=receive)
            bridge_state = await resolve_auth_bridge_state(
                request,
                settings=self.settings,
                session_core=self.session_core,
            )
            _set_scope_auth_bridge_state(scope, bridge_state)
        await self.app(scope, receive, send)


def install_auth_bridge(
    starlette_app: Starlette,
    *,
    settings: Settings,
    session_core: SessionCore | None = None,
) -> SessionCore:
    """Install or update the read-only auth bridge middleware on a Starlette app."""
    resolved_session_core = session_core or create_auth_bridge_session_core(settings)
    setattr(starlette_app.state, AUTH_BRIDGE_SESSION_CORE_STATE_ATTR, resolved_session_core)
    setattr(starlette_app.state, AUTH_BRIDGE_SETTINGS_STATE_ATTR, settings)

    bridge_middleware = Middleware(
        AuthBridgeMiddleware,
        settings=settings,
        session_core=resolved_session_core,
    )
    for index, middleware in enumerate(starlette_app.user_middleware):
        if middleware.cls is AuthBridgeMiddleware:
            starlette_app.user_middleware[index] = bridge_middleware
            starlette_app.middleware_stack = None
            break
    else:
        starlette_app.add_middleware(
            AuthBridgeMiddleware,
            settings=settings,
            session_core=resolved_session_core,
        )

    return resolved_session_core


def create_auth_bridge_session_core(settings: Settings) -> SessionCore:
    """Create a session core for NiceGUI using the shared API signing/store format."""
    redis_client = cast(
        "RedisSessionBackend",
        redis_asyncio.Redis.from_url(settings.redis_url),
    )
    return create_session_core(settings, redis_client)


async def resolve_auth_bridge_state(
    request: Request,
    *,
    settings: Settings,
    session_core: SessionCore,
) -> NiceGUIAuthBridgeState:
    """Resolve an API session cookie into a request-local bridge state."""
    cookie_value = request.cookies.get(settings.session_cookie_name)
    if not cookie_value:
        return ANONYMOUS_AUTH_BRIDGE_STATE

    try:
        record = await session_core.read(cookie_value)
    except (InvalidSessionToken, ValueError):
        return ANONYMOUS_AUTH_BRIDGE_STATE

    if record is None:
        return ANONYMOUS_AUTH_BRIDGE_STATE
    return NiceGUIAuthBridgeState(record=record)


def get_auth_bridge_state(request: Request) -> NiceGUIAuthBridgeState:
    """Return the bridge state exposed by the middleware for a Starlette request."""
    bridge_state = getattr(request.state, AUTH_BRIDGE_STATE_ATTR, None)
    if isinstance(bridge_state, NiceGUIAuthBridgeState):
        return bridge_state
    return ANONYMOUS_AUTH_BRIDGE_STATE


def _set_scope_auth_bridge_state(
    scope: Scope,
    bridge_state: NiceGUIAuthBridgeState,
) -> None:
    scope_state = scope.setdefault("state", {})
    scope_state[AUTH_BRIDGE_STATE_ATTR] = bridge_state


def _copy_credential_payload(credential: SessionCredential | None) -> JsonObject | None:
    if credential is None:
        return None
    return deepcopy(credential.payload)
