"""Auth and session routes for the backend API."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import cast

from fastapi import APIRouter, Request, Response, status

from sophia.adapters.auth import (
    SessionCredentials as TuwelSessionCredentials,
)
from sophia.adapters.auth import (
    TissSessionCredentials,
    login_both,
)
from sophia.api.deps import (
    get_session_core,
    get_settings,
    optional_session_record,
    require_csrf,
)
from sophia.api.schemas.auth import (
    AuthLoginRequest,
    AuthSessionResponse,
    SessionTenantResponse,
    SessionUserResponse,
)
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.settings import SettingsResponse
from sophia.api.sessions import (
    InvalidSessionToken,
    SessionCredential,
    SessionRecord,
    SessionSettings,
    SessionTenant,
    SessionUser,
    create_session_record,
)
from sophia.config import Settings

router = APIRouter(tags=["auth"])

type LoginAuthenticator = Callable[[AuthLoginRequest, Settings], Awaitable[LoginIdentity]]


@dataclass(frozen=True, slots=True)
class LoginIdentity:
    user: SessionUser
    tenant: SessionTenant = field(default_factory=SessionTenant)
    settings: SessionSettings = field(default_factory=SessionSettings)
    tuwel_credentials: SessionCredential | None = None
    tiss_credentials: SessionCredential | None = None


@router.post(
    "/auth/login",
    response_model=AuthSessionResponse,
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def login(
    payload: AuthLoginRequest,
    request: Request,
    response: Response,
) -> AuthSessionResponse:
    settings = get_settings(request)
    session_core = get_session_core(request)
    await _delete_existing_session(request)
    identity = await _login_authenticator(request)(payload, settings)
    record = create_session_record(
        user=identity.user,
        tenant=identity.tenant,
        settings=identity.settings,
        tuwel_credentials=identity.tuwel_credentials,
        tiss_credentials=identity.tiss_credentials,
    )
    session_cookie = await session_core.create(record)
    _set_auth_cookies(response, settings, session_cookie, record.csrf_token)
    return _authenticated_response(record)


@router.get("/auth/session", response_model=AuthSessionResponse)
async def read_session(request: Request) -> AuthSessionResponse:
    record = await optional_session_record(request)
    if record is None:
        return AuthSessionResponse(authenticated=False)
    return _authenticated_response(record)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> Response:
    session = await require_csrf(request)
    settings = get_settings(request)
    await get_session_core(request).store.delete(session.session_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookies(response, settings)
    return response


async def default_login_authenticator(
    payload: AuthLoginRequest,
    settings: Settings,
) -> LoginIdentity:
    tuwel_credentials, tiss_credentials = await login_both(
        settings.tuwel_host,
        settings.tiss_host,
        payload.username,
        payload.password,
        payload.mfa_code,
    )
    return LoginIdentity(
        user=SessionUser(id=payload.username, display_name=payload.username),
        tuwel_credentials=_tuwel_credential(tuwel_credentials),
        tiss_credentials=_tiss_credential(tiss_credentials),
    )


def _login_authenticator(request: Request) -> LoginAuthenticator:
    authenticator = getattr(request.app.state, "login_authenticator", None)
    if authenticator is None:
        return default_login_authenticator
    return cast("LoginAuthenticator", authenticator)


async def _delete_existing_session(request: Request) -> None:
    settings = get_settings(request)
    cookie_value = request.cookies.get(settings.session_cookie_name)
    if not cookie_value:
        return
    try:
        await get_session_core(request).delete(cookie_value)
    except InvalidSessionToken:
        return


def _set_auth_cookies(
    response: Response,
    settings: Settings,
    session_cookie: str,
    csrf_token: str,
) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        session_cookie,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=False,
        samesite=settings.session_cookie_samesite,
    )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite=settings.session_cookie_samesite,
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=False,
        samesite=settings.session_cookie_samesite,
    )


def _authenticated_response(record: SessionRecord) -> AuthSessionResponse:
    return AuthSessionResponse(
        authenticated=True,
        user=SessionUserResponse(
            id=record.user.id,
            display_name=record.user.display_name,
            email=record.user.email,
        ),
        tenant=SessionTenantResponse(
            org_id=record.tenant.org_id,
            course_id=record.tenant.course_id,
            cohort_id=record.tenant.cohort_id,
            role=record.tenant.role,
        ),
        settings=SettingsResponse(
            theme=record.settings.theme,
            locale=record.settings.locale,
            selected_course_id=record.settings.selected_course_id,
        ),
        csrf_token=record.csrf_token,
    )


def _tuwel_credential(credentials: TuwelSessionCredentials) -> SessionCredential:
    return SessionCredential(
        payload={
            "moodle_session": credentials.moodle_session,
            "sesskey": credentials.sesskey,
            "host": credentials.host,
            "created_at": credentials.created_at,
            "cookie_name": credentials.cookie_name,
        }
    )


def _tiss_credential(credentials: TissSessionCredentials | None) -> SessionCredential | None:
    if credentials is None:
        return None
    return SessionCredential(
        payload={
            "jsessionid": credentials.jsessionid,
            "tiss_session": credentials.tiss_session,
            "host": credentials.host,
            "created_at": credentials.created_at,
            "cookies": credentials.cookies,
        }
    )
