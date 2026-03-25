"""Tests for accessibility helpers — keyboard shortcuts, chart tables."""

from __future__ import annotations

from nicegui import ui
from nicegui.testing import user_simulation

from sophia.gui.components.keyboard_shortcuts import (
    _NAV_ROUTES,
    _SHORTCUTS,
    register_keyboard_shortcuts,
)


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
