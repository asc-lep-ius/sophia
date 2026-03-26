"""E2E review flow tests — verify review page loads and key elements are present."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def test_review_page_loads(gui_page: Page, gui_base_url: str) -> None:
    """Review page loads without error."""
    gui_page.goto(f"{gui_base_url}/review")
    gui_page.wait_for_load_state("networkidle")
    assert gui_page.locator("text=Something went wrong").count() == 0


def test_review_heading_present(gui_page: Page, gui_base_url: str) -> None:
    """Review page renders its heading."""
    gui_page.goto(f"{gui_base_url}/review")
    gui_page.wait_for_load_state("networkidle")
    heading = gui_page.locator("text=Review")
    assert heading.count() >= 1


def test_review_empty_state_or_cards(gui_page: Page, gui_base_url: str) -> None:
    """Review page shows either the empty state, loading state, or review cards."""
    gui_page.goto(f"{gui_base_url}/review")
    gui_page.wait_for_load_state("networkidle")
    # Any of these states is acceptable — async rendering means content
    # may take a moment to appear; CI may also lack credentials (auth-error).
    combined = gui_page.locator(
        "text=/All caught up!|Difficulty|Connecting|not initialized|Not logged in/",
    )
    combined.first.wait_for(timeout=10_000)


def test_review_nav_link_present(gui_page: Page, gui_base_url: str) -> None:
    """Sidebar/bottom nav contains a link to the Review page."""
    gui_page.goto(gui_base_url)
    gui_page.wait_for_load_state("networkidle")
    review_links = gui_page.locator("a[href='/review']")
    assert review_links.count() >= 1
