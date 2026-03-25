"""Tests for the responsive layout shell."""

from __future__ import annotations

from nicegui import ui
from nicegui.testing import user_simulation

from sophia.gui.layout import NAV_ITEMS, app_shell


class TestNavItems:
    def test_nav_items_count(self) -> None:
        assert len(NAV_ITEMS) == 6

    def test_all_expected_paths_present(self) -> None:
        paths = {item["path"] for item in NAV_ITEMS}
        expected = {"/", "/study", "/review", "/search", "/chronos", "/calibration"}
        assert paths == expected

    def test_all_items_have_required_keys(self) -> None:
        for item in NAV_ITEMS:
            assert "label" in item
            assert "icon" in item
            assert "path" in item


class TestAppShell:
    async def test_shell_renders_sidebar_with_sophia_label(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                app_shell(lambda: ui.label("Main Content"))

            await user.open("/")
            await user.should_see("Sophia")
            await user.should_see("Main Content")

    async def test_shell_renders_all_nav_labels(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                app_shell(lambda: ui.label("test"))

            await user.open("/")
            for item in NAV_ITEMS:
                await user.should_see(item["label"])
