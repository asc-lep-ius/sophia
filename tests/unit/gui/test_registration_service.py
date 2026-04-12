"""Tests for GUI registration service wrappers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sophia.domain.errors import AuthError
from sophia.domain.models import (
    FavoriteCourse,
    RegistrationGroup,
    RegistrationResult,
    RegistrationStatus,
    RegistrationTarget,
    RegistrationType,
)

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer

_PATCH_BASE = "sophia.gui.services.registration_service"
_COURSE = "186.813"
_SEMESTER = "2026S"


def _make_favorite(**overrides: Any) -> FavoriteCourse:
    defaults: dict[str, Any] = {
        "course_number": _COURSE,
        "title": "Algorithms",
        "course_type": "VU",
        "semester": _SEMESTER,
        "hours": 4.0,
        "ects": 6.0,
        "lva_registered": False,
        "group_registered": False,
        "exam_registered": False,
    }
    defaults.update(overrides)
    return FavoriteCourse(**defaults)


def _make_target(**overrides: Any) -> RegistrationTarget:
    defaults: dict[str, Any] = {
        "course_number": _COURSE,
        "semester": _SEMESTER,
        "registration_type": RegistrationType.LVA,
        "title": "Algorithms",
        "registration_start": "01.03.2026 08:00",
        "registration_end": "15.03.2026 23:59",
        "status": RegistrationStatus.OPEN,
    }
    defaults.update(overrides)
    return RegistrationTarget(**defaults)


def _make_group(**overrides: Any) -> RegistrationGroup:
    defaults: dict[str, Any] = {
        "group_id": "g1",
        "name": "Group A",
        "day": "Tuesday",
        "time_start": "14:00",
        "time_end": "16:00",
        "location": "EI 7",
        "capacity": 30,
        "enrolled": 23,
        "status": RegistrationStatus.OPEN,
        "register_button_id": "btn_1",
    }
    defaults.update(overrides)
    return RegistrationGroup(**defaults)


def _make_result(**overrides: Any) -> RegistrationResult:
    defaults: dict[str, Any] = {
        "course_number": _COURSE,
        "registration_type": RegistrationType.LVA,
        "success": True,
        "group_name": "",
        "message": "Registered successfully",
        "attempted_at": "2026-03-01T08:00:00",
    }
    defaults.update(overrides)
    return RegistrationResult(**defaults)


# -- get_favorites -----------------------------------------------------------


class TestGetFavorites:
    @pytest.mark.asyncio
    async def test_no_session_returns_no_session_status(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.registration_service import get_favorites

        with patch(f"{_PATCH_BASE}._load_credentials", return_value=None):
            result = await get_favorites(mock_container)

        assert result.status == "no_session"
        assert result.favorites == []

    @pytest.mark.asyncio
    async def test_returns_favorites_on_success(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.registration_service import get_favorites

        expected = [_make_favorite()]
        mock_adapter = MagicMock()
        mock_adapter.get_favorites = AsyncMock(return_value=expected)

        with (
            patch(f"{_PATCH_BASE}._load_credentials", return_value=MagicMock()),
            patch(f"{_PATCH_BASE}._make_adapter", return_value=mock_adapter),
        ):
            result = await get_favorites(mock_container, semester=_SEMESTER)

        assert result.status == "success"
        assert result.favorites == expected

    @pytest.mark.asyncio
    async def test_auth_error_returns_auth_expired(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.registration_service import get_favorites

        mock_adapter = MagicMock()
        mock_adapter.get_favorites = AsyncMock(side_effect=AuthError("expired"))

        with (
            patch(f"{_PATCH_BASE}._load_credentials", return_value=MagicMock()),
            patch(f"{_PATCH_BASE}._make_adapter", return_value=mock_adapter),
        ):
            result = await get_favorites(mock_container)

        assert result.status == "auth_expired"

    @pytest.mark.asyncio
    async def test_generic_error_returns_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.registration_service import get_favorites

        mock_adapter = MagicMock()
        mock_adapter.get_favorites = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch(f"{_PATCH_BASE}._load_credentials", return_value=MagicMock()),
            patch(f"{_PATCH_BASE}._make_adapter", return_value=mock_adapter),
        ):
            result = await get_favorites(mock_container)

        assert result.status == "error"
        assert "boom" in (result.error_message or "")


# -- get_registration_status -------------------------------------------------


class TestGetRegistrationStatus:
    @pytest.mark.asyncio
    async def test_no_session_returns_no_session(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.registration_service import get_registration_status

        with patch(f"{_PATCH_BASE}._load_credentials", return_value=None):
            result = await get_registration_status(mock_container, _COURSE, _SEMESTER)

        assert result.status == "no_session"

    @pytest.mark.asyncio
    async def test_returns_target_on_success(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.registration_service import get_registration_status

        target = _make_target()
        mock_adapter = MagicMock()
        mock_adapter.get_registration_status = AsyncMock(return_value=target)

        with (
            patch(f"{_PATCH_BASE}._load_credentials", return_value=MagicMock()),
            patch(f"{_PATCH_BASE}._make_adapter", return_value=mock_adapter),
        ):
            result = await get_registration_status(mock_container, _COURSE, _SEMESTER)

        assert result.status == "success"
        assert result.target == target


# -- get_groups --------------------------------------------------------------


class TestGetGroups:
    @pytest.mark.asyncio
    async def test_no_session_returns_no_session(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.registration_service import get_groups

        with patch(f"{_PATCH_BASE}._load_credentials", return_value=None):
            result = await get_groups(mock_container, _COURSE, _SEMESTER)

        assert result.status == "no_session"
        assert result.groups == []

    @pytest.mark.asyncio
    async def test_returns_groups_on_success(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.registration_service import get_groups

        expected = [_make_group()]
        mock_adapter = MagicMock()
        mock_adapter.get_groups = AsyncMock(return_value=expected)

        with (
            patch(f"{_PATCH_BASE}._load_credentials", return_value=MagicMock()),
            patch(f"{_PATCH_BASE}._make_adapter", return_value=mock_adapter),
        ):
            result = await get_groups(mock_container, _COURSE, _SEMESTER)

        assert result.status == "success"
        assert result.groups == expected


# -- register_course ---------------------------------------------------------


class TestRegisterCourse:
    @pytest.mark.asyncio
    async def test_no_session_returns_no_session(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.registration_service import register_course

        with patch(f"{_PATCH_BASE}._load_credentials", return_value=None):
            result = await register_course(mock_container, _COURSE, _SEMESTER)

        assert result.status == "no_session"

    @pytest.mark.asyncio
    async def test_successful_registration(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.registration_service import register_course

        reg_result = _make_result()
        mock_adapter = MagicMock()
        mock_adapter.register = AsyncMock(return_value=reg_result)

        with (
            patch(f"{_PATCH_BASE}._load_credentials", return_value=MagicMock()),
            patch(f"{_PATCH_BASE}._make_adapter", return_value=mock_adapter),
        ):
            result = await register_course(mock_container, _COURSE, _SEMESTER, group_id="g1")

        assert result.status == "success"
        assert result.registration_result == reg_result
        mock_adapter.register.assert_awaited_once_with(_COURSE, _SEMESTER, "g1")

    @pytest.mark.asyncio
    async def test_auth_error_returns_auth_expired(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.registration_service import register_course

        mock_adapter = MagicMock()
        mock_adapter.register = AsyncMock(side_effect=AuthError("session expired"))

        with (
            patch(f"{_PATCH_BASE}._load_credentials", return_value=MagicMock()),
            patch(f"{_PATCH_BASE}._make_adapter", return_value=mock_adapter),
        ):
            result = await register_course(mock_container, _COURSE, _SEMESTER)

        assert result.status == "auth_expired"


# -- get_exam_dates ----------------------------------------------------------


class TestGetExamDates:
    @pytest.mark.asyncio
    async def test_returns_exam_dates(self, mock_container: AppContainer) -> None:
        from sophia.domain.models import TissExamDate
        from sophia.gui.services.registration_service import get_exam_dates

        expected = [
            TissExamDate(
                exam_id="e1",
                course_number=_COURSE,
                title="Final",
                date_start="2026-06-20",
                date_end="2026-06-20",
                registration_start="2026-05-01",
                registration_end="2026-06-15",
                mode="WRITTEN",
            )
        ]
        mock_container.tiss.get_exam_dates = AsyncMock(return_value=expected)

        result = await get_exam_dates(mock_container, _COURSE)

        assert result == expected
        mock_container.tiss.get_exam_dates.assert_awaited_once_with(_COURSE)

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, mock_container: AppContainer) -> None:
        from sophia.gui.services.registration_service import get_exam_dates

        mock_container.tiss.get_exam_dates = AsyncMock(side_effect=RuntimeError("down"))

        result = await get_exam_dates(mock_container, _COURSE)

        assert result == []
