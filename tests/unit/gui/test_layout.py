"""Tests for the responsive layout shell."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

import pytest
from nicegui import ui
from nicegui.testing import user_simulation

from sophia.gui.layout import NAV_ITEMS, app_shell
from sophia.gui.state.storage_map import TAB_STUDY_SESSION_IDS, TIER_MAP

if TYPE_CHECKING:
    from collections.abc import Iterator


class TestNavItems:
    def test_nav_items_count(self) -> None:
        assert len(NAV_ITEMS) == 9

    def test_all_expected_paths_present(self) -> None:
        paths = {item["path"] for item in NAV_ITEMS}
        expected = {
            "/",
            "/study",
            "/review",
            "/search",
            "/chronos",
            "/calibration",
            "/lectures",
            "/register",
            "/settings",
        }
        assert paths == expected

    def test_all_items_have_required_keys(self) -> None:
        for item in NAV_ITEMS:
            assert "label" in item
            assert "icon" in item
            assert "path" in item


class TestAppShell:
    @pytest.fixture(autouse=True)
    def _patch_course_selector(self) -> Iterator[None]:
        with patch("sophia.gui.layout.render_course_selector", new_callable=AsyncMock) as mock:
            self._mock_selector = mock
            yield

    async def test_shell_renders_sidebar_with_sophia_label(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            async def index() -> None:
                await app_shell(lambda: ui.label("Main Content"))

            await user.open("/")
            await user.should_see("Sophia")
            await user.should_see("Main Content")

    async def test_shell_registers_keyboard_shortcuts(self) -> None:
        with patch("sophia.gui.layout.register_keyboard_shortcuts") as mock_register:
            async with user_simulation() as user:

                @ui.page("/")
                async def index() -> None:
                    await app_shell(lambda: ui.label("test"))

                await user.open("/")
                mock_register.assert_called_once()

    async def test_shell_renders_all_nav_labels(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            async def index() -> None:
                await app_shell(lambda: ui.label("test"))

            await user.open("/")
            for item in NAV_ITEMS:
                await user.should_see(item["label"])

    async def test_shell_awaits_async_content_fn(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            async def index() -> None:
                async def _async_content() -> None:
                    ui.label("Async Shell Content")

                await app_shell(_async_content)

            await user.open("/")
            await user.should_see("Async Shell Content")

    async def test_shell_renders_course_selector_in_sidebar(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            async def index() -> None:
                await app_shell(lambda: ui.label("test"))

            await user.open("/")
            self._mock_selector.assert_awaited_once()


class TestStorageMapSessionIds:
    def test_tab_study_session_ids_constant_exists(self) -> None:
        assert TAB_STUDY_SESSION_IDS == "study_session_ids"

    def test_tab_study_session_ids_in_tier_map(self) -> None:
        assert TAB_STUDY_SESSION_IDS in TIER_MAP["tab"]
