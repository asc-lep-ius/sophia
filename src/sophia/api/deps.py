"""FastAPI dependencies for current request and authenticated session scope."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, cast

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from sophia.api.context import get_request_context
from sophia.api.schemas.common import CohortScope, LearningPathScope, OrgScope, RoleScope, UserScope
from sophia.api.sessions import InvalidSessionToken, SessionCore, SessionRecord
from sophia.api.transactions import get_transaction_stack
from sophia.domain.errors import AuthError
from sophia.infra.org_context import DEFAULT_ORG_ID

if TYPE_CHECKING:
    from sophia.config import Settings
    from sophia.infra.di import AppContainer

_SESSION_STATE_ATTR = "sophia_db_session"
_SESSION_RECORD_STATE_ATTR = "sophia_session_record"
_SESSION_LOADED_STATE_ATTR = "sophia_session_loaded"
_REQUESTED_WITH_VALUES = frozenset({"fetch", "xmlhttprequest"})


def get_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        msg = "API settings are not configured"
        raise RuntimeError(msg)
    return cast("Settings", settings)


def get_session_core(request: Request) -> SessionCore:
    session_core = getattr(request.app.state, "session_core", None)
    if session_core is None:
        msg = "session core is not configured"
        raise RuntimeError(msg)
    return cast("SessionCore", session_core)


def get_app_container(request: Request) -> AppContainer:
    app_container = getattr(request.app.state, "app_container", None)
    if app_container is None:
        msg = "app container is not configured"
        raise RuntimeError(msg)
    return cast("AppContainer", app_container)


async def request_session(request: Request) -> AsyncSession:
    """Return the one session this request runs in, opening it on first use.

    The session is entered into the request's transaction stack, which
    :class:`~sophia.api.transactions.TransactionalRoute` closes inside the route
    handler. Two dependencies asking for a session in the same request get the
    same one, so the request stays a single transaction.
    """
    existing = getattr(request.state, _SESSION_STATE_ATTR, None)
    if isinstance(existing, AsyncSession):
        return existing

    context = get_request_context()
    org_id = context.org_id if context is not None else DEFAULT_ORG_ID
    session = await get_transaction_stack(request).enter_async_context(
        get_app_container(request).session(org_id=org_id),
    )
    setattr(request.state, _SESSION_STATE_ATTR, session)
    return session


async def optional_session_record(request: Request) -> SessionRecord | None:
    loaded = getattr(request.state, _SESSION_LOADED_STATE_ATTR, False)
    if loaded is True:
        cached_record = getattr(request.state, _SESSION_RECORD_STATE_ATTR, None)
        if isinstance(cached_record, SessionRecord):
            return cached_record
        return None

    settings = get_settings(request)
    cookie_value = request.cookies.get(settings.session_cookie_name)
    record: SessionRecord | None = None
    if cookie_value:
        try:
            record = await get_session_core(request).refresh(cookie_value)
        except InvalidSessionToken:
            record = None

    cache_session_record(request, record)
    return record


async def current_session_record(request: Request) -> SessionRecord:
    record = await optional_session_record(request)
    if record is None:
        raise AuthError("Authentication required")
    return record


def cache_session_record(request: Request, record: SessionRecord | None) -> None:
    setattr(request.state, _SESSION_LOADED_STATE_ATTR, True)
    setattr(request.state, _SESSION_RECORD_STATE_ATTR, record)


async def require_csrf(request: Request) -> SessionRecord:
    session = await current_session_record(request)
    requested_with = request.headers.get("x-requested-with", "").strip().lower()
    csrf_token = request.headers.get("x-csrf-token", "").strip()
    if requested_with not in _REQUESTED_WITH_VALUES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    if not csrf_token or not secrets.compare_digest(csrf_token, session.csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    return session


async def require_learning_path_scope(
    request: Request,
    learning_path_id: int | str,
) -> SessionRecord:
    session = await current_session_record(request)
    ensure_learning_path_scope(session, learning_path_id)
    return session


async def require_effective_learning_path_id(
    request: Request,
    learning_path_id: int | None,
) -> int:
    if learning_path_id is not None:
        await require_learning_path_scope(request, learning_path_id)
        return learning_path_id
    session = await current_session_record(request)
    try:
        return int(session.tenant.learning_path_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN) from exc


async def require_csrf_learning_path_scope(
    request: Request,
    learning_path_id: int | str,
) -> SessionRecord:
    session = await require_csrf(request)
    ensure_learning_path_scope(session, learning_path_id)
    return session


def ensure_learning_path_scope(session: SessionRecord, learning_path_id: int | str) -> None:
    if session.tenant.learning_path_id != str(learning_path_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


async def current_org(request: Request) -> OrgScope:
    session = await optional_session_record(request)
    if session is not None:
        return OrgScope(id=session.tenant.org_id, display_name=session.tenant.org_id)
    context = get_request_context()
    return OrgScope(id=context.org_id if context else "local", display_name="Local")


async def current_learning_path(request: Request) -> LearningPathScope:
    session = await optional_session_record(request)
    if session is not None:
        return LearningPathScope(
            id=session.tenant.learning_path_id,
            display_name=session.tenant.learning_path_id,
        )
    context = get_request_context()
    return LearningPathScope(
        id=context.learning_path_id if context else "default-learning-path",
        display_name="Default Learning Path",
    )


async def current_cohort(request: Request) -> CohortScope:
    session = await optional_session_record(request)
    if session is not None:
        cohort_id = session.tenant.cohort_id or "default-cohort"
        return CohortScope(id=cohort_id, display_name=cohort_id)
    context = get_request_context()
    return CohortScope(
        id=context.cohort_id if context else "default-cohort",
        display_name="Default Cohort",
    )


async def current_user(request: Request) -> UserScope:
    session = await optional_session_record(request)
    if session is not None:
        return UserScope(id=session.user.id, display_name=session.user.display_name)
    context = get_request_context()
    return UserScope(
        id=context.user_id if context else "anonymous",
        display_name="Anonymous",
    )


async def current_role(request: Request) -> RoleScope:
    session = await optional_session_record(request)
    if session is not None:
        return RoleScope(value=session.tenant.role)
    context = get_request_context()
    return RoleScope(value=context.role if context else "student")
