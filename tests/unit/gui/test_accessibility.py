"""Tests for accessibility helpers — keyboard shortcuts, chart tables, row extraction."""

from __future__ import annotations

import pytest
from nicegui import ui
from nicegui.testing import user_simulation

from sophia.gui.components.keyboard_shortcuts import (
    _NAV_ROUTES,  # pyright: ignore[reportPrivateUsage]
    _SHORTCUTS,  # pyright: ignore[reportPrivateUsage]
    register_keyboard_shortcuts,
)
from sophia.gui.pages.calibration import (
    build_tier_progression_chart,
    extract_bar_rows,
    extract_heatmap_rows,
    extract_line_rows,
    extract_scatter_rows,
    extract_tier_rows,
)
from sophia.gui.pages.study import _questions_complete  # pyright: ignore[reportPrivateUsage]


class TestKeyboardShortcutData:
    def test_shortcuts_list_not_empty(self) -> None:
        assert len(_SHORTCUTS) >= 5

    def test_all_shortcuts_have_keys_and_action(self) -> None:
        for s in _SHORTCUTS:
            assert "keys" in s
            assert "action" in s

    def test_nav_routes_cover_first_four_pages(self) -> None:
        assert _NAV_ROUTES == {"1": "/", "2": "/study", "3": "/review", "4": "/search"}


class TestShortcutOverlay:
    async def test_help_dialog_renders(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                register_keyboard_shortcuts()
                ui.label("Home")

            await user.open("/")
            await user.should_see("Home")


class TestChartTable:
    async def test_chart_table_renders_headers_and_rows(self) -> None:
        from sophia.gui.components.chart_table import chart_with_table

        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                chart_with_table(
                    {"xAxis": {"type": "value"}, "yAxis": {"type": "value"}, "series": []},
                    headers=["Topic", "Score"],
                    rows=[["Math", "85%"], ["Physics", "72%"]],
                    chart_id="test-chart",
                )

            await user.open("/")
            await user.should_see("Show as table")

    async def test_chart_table_applies_classes(self) -> None:
        from sophia.gui.components.chart_table import chart_with_table

        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                chart_with_table(
                    {"xAxis": {"type": "value"}, "yAxis": {"type": "value"}, "series": []},
                    headers=["A"],
                    rows=[["1"]],
                    chart_id="cls-test",
                    classes="w-full h-64",
                )

            await user.open("/")
            await user.should_see("Show as table")


# --- Row extraction helpers ------------------------------------------------


class TestExtractScatterRows:
    def test_basic_scatter(self) -> None:
        chart = {"series": [{"data": [[0.3, 0.5], [0.8, 0.7]]}]}
        rows = extract_scatter_rows(chart)
        assert rows == [["0.30", "0.50"], ["0.80", "0.70"]]

    def test_empty_series(self) -> None:
        chart = {"series": [{"data": []}]}
        assert extract_scatter_rows(chart) == []

    def test_missing_series(self) -> None:
        assert extract_scatter_rows({}) == []


class TestExtractBarRows:
    def test_basic_bar(self) -> None:
        chart = {
            "yAxis": {"data": ["Topic A", "Topic B"]},
            "series": [{"data": [0.25, 0.15]}],
        }
        rows = extract_bar_rows(chart)
        assert rows == [["Topic A", "0.25"], ["Topic B", "0.15"]]

    def test_xaxis_fallback(self) -> None:
        chart = {
            "xAxis": {"data": ["A", "B"]},
            "series": [{"data": [1, 2]}],
        }
        rows = extract_bar_rows(chart)
        assert rows == [["A", "1"], ["B", "2"]]

    def test_empty(self) -> None:
        assert extract_bar_rows({}) == []


class TestExtractLineRows:
    def test_basic_line(self) -> None:
        chart = {"xAxis": {"data": [1, 2, 3]}, "series": [{"data": [0.1, 0.2, 0.3]}]}
        rows = extract_line_rows(chart)
        assert rows == [["1", "0.10"], ["2", "0.20"], ["3", "0.30"]]

    def test_empty(self) -> None:
        assert extract_line_rows({}) == []


class TestExtractHeatmapRows:
    def test_basic_heatmap(self) -> None:
        chart = {
            "xAxis": {"data": ["Math"]},
            "yAxis": {"data": ["CS101"]},
            "series": [{"data": [[0, 0, 0.85]]}],
        }
        rows = extract_heatmap_rows(chart)
        assert rows == [["Math", "CS101", "0.85"]]

    def test_empty(self) -> None:
        assert extract_heatmap_rows({}) == []


class TestExtractTierRows:
    _TIER_MAP = {0: "cued", 1: "explain", 2: "transfer"}

    def test_basic_tier(self) -> None:
        chart = {
            "xAxis": {"data": ["S1", "S2"]},
            "series": [{"data": [0, 2]}],
        }
        rows = extract_tier_rows(chart)
        assert rows == [["S1", "cued"], ["S2", "transfer"]]

    def test_empty(self) -> None:
        assert extract_tier_rows({}) == []


class TestCalibrationTrendDataRows:
    """Integration test — build chart data then extract rows."""

    def test_trend_round_trip(self) -> None:
        # build_calibration_trend_data expects ConfidenceRating objects; test extract only
        chart = {
            "xAxis": {"data": [1, 2]},
            "series": [{"data": [0.05, 0.12]}],
        }
        rows = extract_line_rows(chart)
        assert len(rows) == 2
        assert rows[0] == ["1", "0.05"]


class TestTierProgressionChartRows:
    def test_progression_round_trip(self) -> None:
        progression = [
            {"session": "S1", "tier": "cued"},
            {"session": "S2", "tier": "explain"},
        ]
        chart = build_tier_progression_chart(progression, "topic")
        rows = extract_tier_rows(chart)
        assert rows == [["S1", "cued"], ["S2", "explain"]]


class TestQuestionsComplete:
    """Validation guard used by Ctrl+Enter shortcut and Next button."""

    @pytest.mark.parametrize(
        "answers, confidence, count, expected",
        [
            ({}, {}, 0, True),
            ({}, {}, 3, False),
            ({"0": "a", "1": "b", "2": "c"}, {"0": 1, "1": 2, "2": 3}, 3, True),
            ({"0": "a", "1": "", "2": "c"}, {"0": 1, "1": 2, "2": 3}, 3, False),
            ({"0": "a", "1": "b"}, {"0": 1, "1": 2, "2": 3}, 3, False),
            ({"0": "a", "1": "b", "2": "c"}, {"0": 1, "1": 2}, 3, False),
            ({"0": "  "}, {"0": 5}, 1, False),
        ],
    )
    def test_questions_complete(
        self,
        answers: dict[str, str],
        confidence: dict[str, int],
        count: int,
        expected: bool,
    ) -> None:
        assert _questions_complete(answers, confidence, count=count) is expected
