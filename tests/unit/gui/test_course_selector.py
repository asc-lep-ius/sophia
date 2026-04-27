"""Tests for the course_selector component."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator


@dataclass
class _FakeSummary:
    course_id: int
    course_name: str
    upcoming_count: int = 0
    overdue_count: int = 0
    blind_spot_count: int = 0
    avg_calibration_error: float | None = None
    hours_this_week: float = 0.0
    topics_total: int = 0
    topics_rated: int = 0
    days_until_nearest: int | None = None
    health: str = "green"


_MODULE = "sophia.gui.components.course_selector"


class _UnavailableTabStorage:
    """Simulate NiceGUI tab storage before a client connection exists."""

    def get(self, _key: str) -> None:
        raise RuntimeError("app.storage.tab can only be used with a client connection")


@pytest.fixture()
def _patches() -> Generator[dict[str, Any]]:
    """Patch all external dependencies of course_selector."""
    with (
        patch(f"{_MODULE}.get_container") as mock_get_container,
        patch(f"{_MODULE}.get_course_summaries", new_callable=AsyncMock) as mock_summaries,
        patch(f"{_MODULE}.get_current_course") as mock_get_current,
        patch(f"{_MODULE}.set_current_course") as mock_set_current,
        patch(f"{_MODULE}.init_course_for_tab") as mock_init_tab,
        patch(f"{_MODULE}.ui") as mock_ui,
    ):
        mock_ui.element.return_value.__enter__ = MagicMock()
        mock_ui.element.return_value.__exit__ = MagicMock()

        yield {
            "get_container": mock_get_container,
            "get_course_summaries": mock_summaries,
            "get_current_course": mock_get_current,
            "set_current_course": mock_set_current,
            "init_course_for_tab": mock_init_tab,
            "ui": mock_ui,
        }


class TestNoContainer:
    @pytest.mark.asyncio
    async def test_shows_not_connected(self, _patches: dict[str, Any]) -> None:
        _patches["get_container"].return_value = None

        from sophia.gui.components.course_selector import render_course_selector

        await render_course_selector()

        _patches["ui"].label.assert_called_once_with("Not connected")
        _patches["ui"].select.assert_not_called()

    @pytest.mark.asyncio
    async def test_init_tab_still_called(self, _patches: dict[str, Any]) -> None:
        _patches["get_container"].return_value = None

        from sophia.gui.components.course_selector import render_course_selector

        await render_course_selector()

        _patches["init_course_for_tab"].assert_called_once()

    @pytest.mark.asyncio
    async def test_pre_client_tab_storage_does_not_crash_initial_render(self) -> None:
        storage = MagicMock()
        storage.tab = _UnavailableTabStorage()
        storage.user = {}

        with (
            patch(f"{_MODULE}.get_container", return_value=None),
            patch(f"{_MODULE}.ui") as mock_ui,
            patch("sophia.gui.state.course_state.app") as mock_app,
        ):
            mock_ui.element.return_value.__enter__ = MagicMock()
            mock_ui.element.return_value.__exit__ = MagicMock()
            mock_app.storage = storage

            from sophia.gui.components.course_selector import render_course_selector

            await render_course_selector()

        mock_ui.label.assert_called_once_with("Not connected")


class TestEmptyCourses:
    @pytest.mark.asyncio
    async def test_shows_no_courses_message(self, _patches: dict[str, Any]) -> None:
        _patches["get_container"].return_value = MagicMock()
        _patches["get_course_summaries"].return_value = []

        from sophia.gui.components.course_selector import render_course_selector

        await render_course_selector()

        _patches["ui"].label.assert_called_once_with("No courses available")
        _patches["ui"].select.assert_not_called()


class TestFetchError:
    @pytest.mark.asyncio
    async def test_shows_error_message(self, _patches: dict[str, Any]) -> None:
        _patches["get_container"].return_value = MagicMock()
        _patches["get_course_summaries"].side_effect = RuntimeError("db gone")

        from sophia.gui.components.course_selector import render_course_selector

        await render_course_selector()

        _patches["ui"].label.assert_called_once_with("Could not load courses")
        _patches["ui"].select.assert_not_called()


class TestRendersSelect:
    @pytest.mark.asyncio
    async def test_renders_with_correct_options(self, _patches: dict[str, Any]) -> None:
        container = MagicMock()
        _patches["get_container"].return_value = container
        _patches["get_course_summaries"].return_value = [
            _FakeSummary(course_id=1, course_name="Math"),
            _FakeSummary(course_id=2, course_name="Physics"),
        ]
        _patches["get_current_course"].return_value = 1

        from sophia.gui.components.course_selector import render_course_selector

        await render_course_selector()

        _patches["ui"].select.assert_called_once()
        call_kwargs = _patches["ui"].select.call_args.kwargs
        assert call_kwargs["options"] == {1: "Math", 2: "Physics"}
        assert call_kwargs["value"] == 1
        assert call_kwargs["label"] == "Course"

    @pytest.mark.asyncio
    async def test_stale_course_cleared(self, _patches: dict[str, Any]) -> None:
        _patches["get_container"].return_value = MagicMock()
        _patches["get_course_summaries"].return_value = [
            _FakeSummary(course_id=1, course_name="Math"),
        ]
        _patches["get_current_course"].return_value = 999  # stale

        from sophia.gui.components.course_selector import render_course_selector

        await render_course_selector()

        call_kwargs = _patches["ui"].select.call_args.kwargs
        assert call_kwargs["value"] is None


class TestOnChange:
    @pytest.mark.asyncio
    async def test_calls_set_current_course(self, _patches: dict[str, Any]) -> None:
        _patches["get_container"].return_value = MagicMock()
        _patches["get_course_summaries"].return_value = [
            _FakeSummary(course_id=5, course_name="Chemistry"),
        ]
        _patches["get_current_course"].return_value = None

        from sophia.gui.components.course_selector import render_course_selector

        await render_course_selector()

        on_change = _patches["ui"].select.call_args.kwargs["on_change"]
        event = MagicMock()
        event.value = 5
        on_change(event)

        _patches["set_current_course"].assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_ignores_none_value(self, _patches: dict[str, Any]) -> None:
        _patches["get_container"].return_value = MagicMock()
        _patches["get_course_summaries"].return_value = [
            _FakeSummary(course_id=5, course_name="Chemistry"),
        ]
        _patches["get_current_course"].return_value = None

        from sophia.gui.components.course_selector import render_course_selector

        await render_course_selector()

        on_change = _patches["ui"].select.call_args.kwargs["on_change"]
        event = MagicMock()
        event.value = None
        on_change(event)

        _patches["set_current_course"].assert_not_called()
