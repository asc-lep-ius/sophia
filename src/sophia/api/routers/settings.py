"""Authenticated learner settings routes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from fastapi import APIRouter, Request, status

from sophia.api.deps import (
    cache_session_record,
    current_session_record,
    get_session_core,
    require_csrf,
)
from sophia.api.schemas.errors import ErrorEnvelope
from sophia.api.schemas.settings import SettingsPatchRequest, SettingsResponse
from sophia.api.sessions import SessionRecord, SessionSettings
from sophia.api.transactions import TransactionalRoute
from sophia.domain.errors import AuthError

router = APIRouter(tags=["settings"], route_class=TransactionalRoute)


@router.get("/settings", response_model=SettingsResponse)
async def read_settings(request: Request) -> SettingsResponse:
    session = await current_session_record(request)
    return _settings_response(session.settings)


@router.patch(
    "/settings",
    response_model=SettingsResponse,
    responses={status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorEnvelope}},
)
async def patch_settings(
    payload: SettingsPatchRequest,
    request: Request,
) -> SettingsResponse:
    session = await require_csrf(request)
    updated_settings = _patched_settings(session.settings, payload)
    updated_record = _updated_session_record(session, updated_settings)
    saved = await get_session_core(request).store.save(updated_record)
    if not saved:
        cache_session_record(request, None)
        raise AuthError("Authentication required")
    cache_session_record(request, updated_record)
    return _settings_response(updated_settings)


def _updated_session_record(
    session: SessionRecord,
    updated_settings: SessionSettings,
) -> SessionRecord:
    return replace(
        session,
        settings=updated_settings,
        updated_at=_utc_now_iso(),
    )


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _patched_settings(
    current_settings: SessionSettings,
    payload: SettingsPatchRequest,
) -> SessionSettings:
    fields = payload.model_fields_set
    theme = current_settings.theme
    locale = current_settings.locale
    if "theme" in fields and payload.theme is not None:
        theme = payload.theme
    if "locale" in fields and payload.locale is not None:
        locale = payload.locale
    return SessionSettings(
        theme=theme,
        locale=locale,
        selected_learning_path_id=(
            payload.selected_learning_path_id
            if "selected_learning_path_id" in fields
            else current_settings.selected_learning_path_id
        ),
    )


def _settings_response(settings: SessionSettings) -> SettingsResponse:
    return SettingsResponse(
        theme=settings.theme,
        locale=settings.locale,
        selected_learning_path_id=settings.selected_learning_path_id,
    )
