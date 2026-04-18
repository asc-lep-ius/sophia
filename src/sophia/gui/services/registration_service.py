"""GUI-safe wrappers for TISS registration actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

import structlog

from sophia.adapters.auth import TissSessionCredentials, load_tiss_session, tiss_session_path
from sophia.adapters.tiss_registration import TissRegistrationAdapter
from sophia.domain.errors import AuthError, NetworkError

if TYPE_CHECKING:
    from sophia.domain.models import (
        FavoriteCourse,
        RegistrationGroup,
        RegistrationResult,
        RegistrationTarget,
        TissExamDate,
    )
    from sophia.infra.di import AppContainer

log = structlog.get_logger()


# -- Result types ------------------------------------------------------------


@dataclass
class FavoritesResult:
    """Structured result from favorites fetch."""

    status: str  # "success" | "no_session" | "auth_expired" | "error"
    favorites: list[FavoriteCourse] = field(default_factory=list)
    error_message: str | None = None


@dataclass
class StatusResult:
    """Structured result from registration-status fetch."""

    status: str  # "success" | "no_session" | "auth_expired" | "error"
    target: RegistrationTarget | None = None
    error_message: str | None = None


@dataclass
class GroupsResult:
    """Structured result from groups fetch."""

    status: str
    groups: list[RegistrationGroup] = field(default_factory=list)
    error_message: str | None = None


@dataclass
class RegisterResult:
    """Structured result from a registration attempt."""

    status: str
    registration_result: RegistrationResult | None = None
    error_message: str | None = None


# -- Internals ---------------------------------------------------------------


def _load_credentials(settings_config_dir: object) -> TissSessionCredentials | None:
    """Load TISS session credentials from disk."""
    from pathlib import Path

    config_dir = Path(str(settings_config_dir))
    return load_tiss_session(tiss_session_path(config_dir))


def _make_adapter(
    http: object, credentials: TissSessionCredentials, host: str
) -> TissRegistrationAdapter:
    """Create a TissRegistrationAdapter from DI components."""
    import httpx

    return TissRegistrationAdapter(
        http=http if isinstance(http, httpx.AsyncClient) else http,  # type: ignore[arg-type]
        credentials=credentials,
        host=host,
    )


def current_semester() -> str:
    """Infer current TISS semester from the date (e.g., '2026S' or '2025W')."""
    today = date.today()
    if today.month >= 10 or today.month <= 1:
        year = today.year if today.month >= 10 else today.year - 1
        return f"{year}W"
    return f"{today.year}S"


# -- Public API --------------------------------------------------------------


async def get_favorites(
    app: AppContainer,
    *,
    semester: str = "",
) -> FavoritesResult:
    """Fetch TISS favorite courses for the given semester."""
    creds = _load_credentials(app.settings.config_dir)
    if creds is None:
        return FavoritesResult(status="no_session")

    if not semester:
        semester = current_semester()

    adapter = _make_adapter(app.http, creds, app.settings.tiss_host)
    try:
        favorites = await adapter.get_favorites(semester)
        return FavoritesResult(status="success", favorites=favorites)
    except AuthError:
        log.warning("registration_auth_expired")
        return FavoritesResult(status="auth_expired")
    except NetworkError as exc:
        log.warning("registration_network_error")
        return FavoritesResult(status="network_error", error_message=str(exc))
    except Exception as exc:
        log.exception("get_favorites_failed")
        return FavoritesResult(status="error", error_message=str(exc))


async def get_registration_status(
    app: AppContainer,
    course_number: str,
    semester: str,
) -> StatusResult:
    """Fetch registration status for a specific course."""
    creds = _load_credentials(app.settings.config_dir)
    if creds is None:
        return StatusResult(status="no_session")

    adapter = _make_adapter(app.http, creds, app.settings.tiss_host)
    try:
        target = await adapter.get_registration_status(course_number, semester)
        return StatusResult(status="success", target=target)
    except AuthError:
        log.warning("registration_status_auth_expired", course=course_number)
        return StatusResult(status="auth_expired")
    except NetworkError as exc:
        log.warning("registration_network_error", course=course_number)
        return StatusResult(status="network_error", error_message=str(exc))
    except Exception as exc:
        log.exception("get_registration_status_failed", course=course_number)
        return StatusResult(status="error", error_message=str(exc))


async def get_groups(
    app: AppContainer,
    course_number: str,
    semester: str,
) -> GroupsResult:
    """Fetch available groups for a course."""
    creds = _load_credentials(app.settings.config_dir)
    if creds is None:
        return GroupsResult(status="no_session")

    adapter = _make_adapter(app.http, creds, app.settings.tiss_host)
    try:
        groups = await adapter.get_groups(course_number, semester)
        return GroupsResult(status="success", groups=groups)
    except AuthError:
        log.warning("registration_groups_auth_expired", course=course_number)
        return GroupsResult(status="auth_expired")
    except NetworkError as exc:
        log.warning("registration_network_error", course=course_number)
        return GroupsResult(status="network_error", error_message=str(exc))
    except Exception as exc:
        log.exception("get_groups_failed", course=course_number)
        return GroupsResult(status="error", error_message=str(exc))


async def register_course(
    app: AppContainer,
    course_number: str,
    semester: str,
    *,
    group_id: str | None = None,
) -> RegisterResult:
    """Submit a registration for a course (optionally for a specific group)."""
    creds = _load_credentials(app.settings.config_dir)
    if creds is None:
        return RegisterResult(status="no_session")

    adapter = _make_adapter(app.http, creds, app.settings.tiss_host)
    try:
        result = await adapter.register(course_number, semester, group_id)
        return RegisterResult(status="success", registration_result=result)
    except AuthError:
        log.warning("registration_auth_expired", course=course_number)
        return RegisterResult(status="auth_expired")
    except NetworkError as exc:
        log.warning("registration_network_error", course=course_number)
        return RegisterResult(status="network_error", error_message=str(exc))
    except Exception as exc:
        log.exception("register_course_failed", course=course_number)
        return RegisterResult(status="error", error_message=str(exc))


async def get_exam_dates(
    app: AppContainer,
    course_number: str,
) -> list[TissExamDate]:
    """Fetch exam dates via the public TISS API (no auth needed)."""
    try:
        return await app.tiss.get_exam_dates(course_number)
    except Exception:
        log.exception("get_exam_dates_failed", course=course_number)
        return []
