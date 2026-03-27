"""E2E navigation tests — verify all pages are reachable and keyboard nav works."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

PAGES = [
    ("/", "Dashboard"),
    ("/study", "Study"),
    ("/review", "Review"),
    ("/search", "Search"),
    ("/chronos", "Chronos"),
    ("/calibration", "Calibration"),
    ("/settings", "Settings"),
]


@pytest.mark.parametrize("route,title", PAGES)
def test_page_loads(gui_page: Page, gui_base_url: str, route: str, title: str) -> None:
    """Each page loads without showing the error boundary."""
    gui_page.goto(f"{gui_base_url}{route}")
    gui_page.wait_for_load_state("networkidle")
    assert gui_page.locator("text=Something went wrong").count() == 0


@pytest.mark.xfail(reason="NiceGUI keyboard needs internal focus, not via Playwright")
def test_keyboard_nav_ctrl_2_goes_to_study(gui_page: Page, gui_base_url: str) -> None:
    """Ctrl+2 navigates to the Study page."""
    gui_page.goto(gui_base_url)
    gui_page.wait_for_load_state("networkidle")

    # Click body to ensure NiceGUI's keyboard handler has focus
    gui_page.click("body")
    gui_page.keyboard.press("Control+2")
    gui_page.wait_for_load_state("networkidle")
    assert "/study" in gui_page.url


@pytest.mark.xfail(reason="NiceGUI keyboard needs internal focus, not via Playwright")
def test_keyboard_nav_ctrl_3_goes_to_review(gui_page: Page, gui_base_url: str) -> None:
    """Ctrl+3 navigates to the Review page."""
    gui_page.goto(gui_base_url)
    gui_page.wait_for_load_state("networkidle")

    gui_page.click("body")
    gui_page.keyboard.press("Control+3")
    gui_page.wait_for_load_state("networkidle")
    assert "/review" in gui_page.url


def test_skip_to_content_link(gui_page: Page) -> None:
    """Skip-to-content link exists and targets #main-content."""
    link = gui_page.locator("a[href='#main-content']")
    assert link.count() >= 1
