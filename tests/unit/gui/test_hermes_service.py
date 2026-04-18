"""Tests for hermes_service — GUI-safe wrappers for Hermes lecture management."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from sophia.gui.services.hermes_service import (
    ModuleInfo,
    get_lecture_modules,
    get_module_lectures,
)
from sophia.services.hermes_manage import EpisodeStatus


class TestGetLectureModules:
    """Verify get_lecture_modules queries and maps DB rows correctly."""

    @pytest.mark.asyncio
    async def test_returns_module_info_list(self) -> None:
        cursor = AsyncMock()
        cursor.fetchall.return_value = [(101, "s1", "Intro to CS"), (202, "s2", "Algorithms")]
        db = AsyncMock()
        db.execute.return_value = cursor

        result = await get_lecture_modules(db)

        assert result == [
            ModuleInfo(module_id=101, series_id="s1", course_name="Intro to CS"),
            ModuleInfo(module_id=202, series_id="s2", course_name="Algorithms"),
        ]
        db.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_null_course_name_defaults_to_empty(self) -> None:
        cursor = AsyncMock()
        cursor.fetchall.return_value = [(303, "s3", "")]
        db = AsyncMock()
        db.execute.return_value = cursor

        result = await get_lecture_modules(db)

        assert result == [ModuleInfo(module_id=303, series_id="s3", course_name="")]

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_rows(self) -> None:
        cursor = AsyncMock()
        cursor.fetchall.return_value = []
        db = AsyncMock()
        db.execute.return_value = cursor

        assert await get_lecture_modules(db) == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self) -> None:
        db = AsyncMock()
        db.execute.side_effect = Exception("db gone")

        assert await get_lecture_modules(db) == []


class TestGetModuleLectures:
    """Verify get_module_lectures wraps hermes_manage.get_pipeline_status."""

    @pytest.mark.asyncio
    async def test_delegates_to_pipeline_status(self) -> None:
        episodes = [
            EpisodeStatus("e1", "Lecture 1", "completed", None, "completed", "completed"),
        ]
        db = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mock_fn = AsyncMock(return_value=episodes)
            mp.setattr("sophia.gui.services.hermes_service._get_pipeline_status", mock_fn)
            result = await get_module_lectures(db, 42)

        assert result == episodes
        mock_fn.assert_awaited_once_with(db, 42)

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self) -> None:
        db = AsyncMock()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "sophia.gui.services.hermes_service._get_pipeline_status",
                AsyncMock(side_effect=RuntimeError("boom")),
            )
            result = await get_module_lectures(db, 99)

        assert result == []


class TestModuleInfo:
    """Verify the ModuleInfo dataclass."""

    def test_equality(self) -> None:
        a = ModuleInfo(module_id=1, series_id="s1", course_name="CS 101")
        b = ModuleInfo(module_id=1, series_id="s1", course_name="CS 101")
        assert a == b

    def test_fields(self) -> None:
        m = ModuleInfo(module_id=42, series_id="abc", course_name="Advanced SE")
        assert m.module_id == 42
        assert m.series_id == "abc"
        assert m.course_name == "Advanced SE"

    def test_course_name_defaults_to_empty(self) -> None:
        m = ModuleInfo(module_id=1, series_id="s1")
        assert m.course_name == ""
