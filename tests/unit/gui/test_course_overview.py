"""Tests for course overview component rendering helpers."""

from __future__ import annotations

from unittest.mock import patch

from sophia.gui.components.course_overview import (
    _HEALTH_COLORS,
    _HEALTH_ICONS,
    select_course,
)
from sophia.gui.services.overview_service import CourseSummary
from sophia.gui.state.storage_map import USER_CURRENT_COURSE

# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _make_summary(**overrides: object) -> CourseSummary:
    defaults: dict[str, object] = {
        "course_id": 1,
        "course_name": "Test Course",
        "upcoming_count": 0,
        "overdue_count": 0,
        "blind_spot_count": 0,
        "avg_calibration_error": None,
        "hours_this_week": 0.0,
        "topics_total": 0,
        "topics_rated": 0,
        "days_until_nearest": None,
        "health": "green",
    }
    defaults.update(overrides)
    return CourseSummary(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Health color/icon mappings
# ---------------------------------------------------------------------------


class TestHealthMappings:
    def test_all_health_states_have_colors(self) -> None:
        for state in ("green", "yellow", "red"):
            assert state in _HEALTH_COLORS

    def test_all_health_states_have_icons(self) -> None:
        for state in ("green", "yellow", "red"):
            assert state in _HEALTH_ICONS

    def test_colors_are_hex(self) -> None:
        for color in _HEALTH_COLORS.values():
            assert color.startswith("#")
            assert len(color) == 7


# ---------------------------------------------------------------------------
# select_course
# ---------------------------------------------------------------------------


class TestSelectCourse:
    def test_sets_storage_key(self) -> None:
        storage: dict[str, object] = {}
        with (
            patch("sophia.gui.components.course_overview.app") as mock_app,
            patch("sophia.gui.components.course_overview.ui"),
        ):
            mock_app.storage.user = storage
            select_course(42, "Operating Systems")
        assert storage[USER_CURRENT_COURSE] == 42

    def test_notifies_user(self) -> None:
        storage: dict[str, object] = {}
        with (
            patch("sophia.gui.components.course_overview.app") as mock_app,
            patch("sophia.gui.components.course_overview.ui") as mock_ui,
        ):
            mock_app.storage.user = storage
            select_course(7, "Linear Algebra")
        mock_ui.notify.assert_called_once()
        msg = mock_ui.notify.call_args[0][0]
        assert "Linear Algebra" in msg

    def test_overwrites_previous_selection(self) -> None:
        storage: dict[str, object] = {USER_CURRENT_COURSE: 1}
        with (
            patch("sophia.gui.components.course_overview.app") as mock_app,
            patch("sophia.gui.components.course_overview.ui"),
        ):
            mock_app.storage.user = storage
            select_course(99, "Databases")
        assert storage[USER_CURRENT_COURSE] == 99
