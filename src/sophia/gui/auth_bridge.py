"""Read-only bridge from API session cookies into legacy NiceGUI requests."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from redis import asyncio as redis_asyncio
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
AUTH_BRIDGE_STACK_WRAPPER_STATE_ATTR = "sophia_auth_bridge_stack_wrapper_installed"


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
        settings: Settings | None = None,
        session_core: SessionCore | None = None,
        starlette_app: Starlette | None = None,
    ) -> None:
        if starlette_app is None and (settings is None or session_core is None):
            msg = "AuthBridgeMiddleware requires settings/session_core or starlette_app"
            raise ValueError(msg)
        self.app = app
        self.settings = settings
        self.session_core = session_core
        self.starlette_app = starlette_app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            bridge_state = ANONYMOUS_AUTH_BRIDGE_STATE
            dependencies = self._dependencies()
            if dependencies is not None:
                settings, session_core = dependencies
                request = Request(scope, receive=receive)
                bridge_state = await resolve_auth_bridge_state(
                    request,
                    settings=settings,
                    session_core=session_core,
                )
            _set_scope_auth_bridge_state(scope, bridge_state)
        await self.app(scope, receive, send)

    def _dependencies(self) -> tuple[Settings, SessionCore] | None:
        if self.starlette_app is not None:
            settings = getattr(
                self.starlette_app.state,
                AUTH_BRIDGE_SETTINGS_STATE_ATTR,
                None,
            )
            session_core = getattr(
                self.starlette_app.state,
                AUTH_BRIDGE_SESSION_CORE_STATE_ATTR,
                None,
            )
            if settings is not None and session_core is not None:
                return cast("Settings", settings), cast("SessionCore", session_core)

        if self.settings is not None and self.session_core is not None:
            return self.settings, self.session_core
        return None


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

    if _has_auth_bridge_user_middleware(starlette_app):
        return resolved_session_core

    if starlette_app.middleware_stack is None:
        starlette_app.add_middleware(AuthBridgeMiddleware, starlette_app=starlette_app)
        return resolved_session_core

    _install_auth_bridge_stack_wrapper(starlette_app)

    return resolved_session_core


def _has_auth_bridge_user_middleware(starlette_app: Starlette) -> bool:
    return any(
        middleware.cls is AuthBridgeMiddleware for middleware in starlette_app.user_middleware
    )


def _install_auth_bridge_stack_wrapper(starlette_app: Starlette) -> None:
    if getattr(starlette_app.state, AUTH_BRIDGE_STACK_WRAPPER_STATE_ATTR, False):
        return

    middleware_stack = starlette_app.middleware_stack
    if middleware_stack is None:
        return

    starlette_app.middleware_stack = AuthBridgeMiddleware(
        middleware_stack,
        starlette_app=starlette_app,
    )
    setattr(starlette_app.state, AUTH_BRIDGE_STACK_WRAPPER_STATE_ATTR, True)


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
