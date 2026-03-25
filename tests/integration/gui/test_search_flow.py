"""E2E search flow tests — verify search page loads and input is accessible."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def test_search_page_loads(gui_page: Page, gui_base_url: str) -> None:
    """Search page loads without error."""
    gui_page.goto(f"{gui_base_url}/search")
    gui_page.wait_for_load_state("networkidle")
    assert gui_page.locator("text=Something went wrong").count() == 0


def test_search_input_has_aria_label(gui_page: Page, gui_base_url: str) -> None:
    """Search input has an accessible aria-label."""
    gui_page.goto(f"{gui_base_url}/search")
    gui_page.wait_for_load_state("networkidle")
    search_input = gui_page.locator("[aria-label='Search lecture transcripts']")
    assert search_input.count() >= 1


def test_search_input_has_placeholder(gui_page: Page, gui_base_url: str) -> None:
    """Search input has a descriptive placeholder."""
    gui_page.goto(f"{gui_base_url}/search")
    gui_page.wait_for_load_state("networkidle")
    placeholder = gui_page.locator("[placeholder='Enter a search query…']")
    assert placeholder.count() >= 1


def test_search_nav_link_present(gui_page: Page, gui_base_url: str) -> None:
    """Sidebar/bottom nav contains a link to the Search page."""
    gui_page.goto(gui_base_url)
    gui_page.wait_for_load_state("networkidle")
    search_links = gui_page.locator("a[href='/search']")
    assert search_links.count() >= 1


def test_search_main_content_landmark(gui_page: Page, gui_base_url: str) -> None:
    """The #main-content landmark exists on the search page."""
    gui_page.goto(f"{gui_base_url}/search")
    gui_page.wait_for_load_state("networkidle")
    assert gui_page.locator("#main-content").count() == 1
