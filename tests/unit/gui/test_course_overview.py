"""Tests for course overview component rendering helpers."""

from __future__ import annotations

from sophia.gui.components.course_overview import (
    _HEALTH_COLORS,
    _HEALTH_ICONS,
)
from sophia.gui.services.overview_service import CourseSummary

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
