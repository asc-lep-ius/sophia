"""TISS registration reads and writes usable from both the API and the GUI.

Promoted out of ``sophia.gui.services.registration_service`` so HTTP routers can
reach these operations without importing the GUI package. Callers get a status
instead of an exception for credential problems, because "TISS is not linked
yet" is an ordinary state of the integration rather than a failed request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import anyio.to_thread
import structlog

from sophia.adapters.auth import TissSessionCredentials, load_tiss_session, tiss_session_path
from sophia.adapters.tiss_registration import TissRegistrationAdapter
from sophia.domain.errors import AuthError, NetworkError
from sophia.domain.models import FavoriteCourse, RegistrationGroup

if TYPE_CHECKING:
    from sophia.domain.models import (
        RegistrationResult,
        RegistrationTarget,
        TissExamDate,
    )
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

STATUS_SUCCESS = "success"
STATUS_NO_SESSION = "no_session"
STATUS_AUTH_EXPIRED = "auth_expired"
STATUS_NETWORK_ERROR = "network_error"
STATUS_ERROR = "error"


@dataclass
class FavoritesResult:
    """Structured result from favorites fetch."""

    status: str
    favorites: list[FavoriteCourse] = field(default_factory=list[FavoriteCourse])
    error_message: str | None = None


@dataclass
class StatusResult:
    """Structured result from registration-status fetch."""

    status: str
    target: RegistrationTarget | None = None
    error_message: str | None = None


@dataclass
class GroupsResult:
    """Structured result from groups fetch."""

    status: str
    groups: list[RegistrationGroup] = field(default_factory=list[RegistrationGroup])
    error_message: str | None = None


@dataclass
class RegisterResult:
    """Structured result from a registration attempt."""

    status: str
    registration_result: RegistrationResult | None = None
    error_message: str | None = None


def current_semester() -> str:
    """Infer the current TISS semester from the date (e.g. '2026S' or '2025W')."""
    today = date.today()  # noqa: DTZ011 - semester boundaries are local calendar dates
    if today.month >= 10 or today.month <= 1:
        year = today.year if today.month >= 10 else today.year - 1
        return f"{year}W"
    return f"{today.year}S"


async def get_favorites(app: AppContainer, *, semester: str = "") -> FavoritesResult:
    """Fetch TISS favorite courses for the given semester."""
    credentials = await _load_credentials(app)
    if credentials is None:
        return FavoritesResult(status=STATUS_NO_SESSION)

    adapter = _make_adapter(app, credentials)
    try:
        favorites = await adapter.get_favorites(semester or current_semester())
    except AuthError:
        log.warning("registration_auth_expired")
        return FavoritesResult(status=STATUS_AUTH_EXPIRED)
    except NetworkError as exc:
        log.warning("registration_network_error")
        return FavoritesResult(status=STATUS_NETWORK_ERROR, error_message=str(exc))
    except Exception as exc:
        log.exception("get_favorites_failed")
        return FavoritesResult(status=STATUS_ERROR, error_message=str(exc))
    return FavoritesResult(status=STATUS_SUCCESS, favorites=favorites)


async def get_registration_status(
    app: AppContainer,
    course_number: str,
    semester: str,
) -> StatusResult:
    """Fetch registration status for a specific course."""
    credentials = await _load_credentials(app)
    if credentials is None:
        return StatusResult(status=STATUS_NO_SESSION)

    adapter = _make_adapter(app, credentials)
    try:
        target = await adapter.get_registration_status(course_number, semester)
    except AuthError:
        log.warning("registration_status_auth_expired", course=course_number)
        return StatusResult(status=STATUS_AUTH_EXPIRED)
    except NetworkError as exc:
        log.warning("registration_network_error", course=course_number)
        return StatusResult(status=STATUS_NETWORK_ERROR, error_message=str(exc))
    except Exception as exc:
        log.exception("get_registration_status_failed", course=course_number)
        return StatusResult(status=STATUS_ERROR, error_message=str(exc))
    return StatusResult(status=STATUS_SUCCESS, target=target)


async def get_groups(app: AppContainer, course_number: str, semester: str) -> GroupsResult:
    """Fetch available groups for a course."""
    credentials = await _load_credentials(app)
    if credentials is None:
        return GroupsResult(status=STATUS_NO_SESSION)

    adapter = _make_adapter(app, credentials)
    try:
        groups = await adapter.get_groups(course_number, semester)
    except AuthError:
        log.warning("registration_groups_auth_expired", course=course_number)
        return GroupsResult(status=STATUS_AUTH_EXPIRED)
    except NetworkError as exc:
        log.warning("registration_network_error", course=course_number)
        return GroupsResult(status=STATUS_NETWORK_ERROR, error_message=str(exc))
    except Exception as exc:
        log.exception("get_groups_failed", course=course_number)
        return GroupsResult(status=STATUS_ERROR, error_message=str(exc))
    return GroupsResult(status=STATUS_SUCCESS, groups=groups)


async def register_course(
    app: AppContainer,
    course_number: str,
    semester: str,
    *,
    group_id: str | None = None,
) -> RegisterResult:
    """Submit a registration for a course, optionally for a specific group."""
    credentials = await _load_credentials(app)
    if credentials is None:
        return RegisterResult(status=STATUS_NO_SESSION)

    adapter = _make_adapter(app, credentials)
    try:
        result = await adapter.register(course_number, semester, group_id)
    except AuthError:
        log.warning("registration_auth_expired", course=course_number)
        return RegisterResult(status=STATUS_AUTH_EXPIRED)
    except NetworkError as exc:
        log.warning("registration_network_error", course=course_number)
        return RegisterResult(status=STATUS_NETWORK_ERROR, error_message=str(exc))
    except Exception as exc:
        log.exception("register_course_failed", course=course_number)
        return RegisterResult(status=STATUS_ERROR, error_message=str(exc))
    return RegisterResult(status=STATUS_SUCCESS, registration_result=result)


async def get_exam_dates(app: AppContainer, course_number: str) -> list[TissExamDate]:
    """Fetch exam dates via the public TISS API, which needs no credentials."""
    try:
        return await app.tiss.get_exam_dates(course_number)
    except Exception:
        log.exception("get_exam_dates_failed", course=course_number)
        return []


async def _load_credentials(app: AppContainer) -> TissSessionCredentials | None:
    config_dir = Path(str(app.settings.config_dir))
    return await anyio.to_thread.run_sync(load_tiss_session, tiss_session_path(config_dir))


def _make_adapter(
    app: AppContainer,
    credentials: TissSessionCredentials,
) -> TissRegistrationAdapter:
    return TissRegistrationAdapter(
        http=app.http,
        credentials=credentials,
        host=app.settings.tiss_host,
    )
