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
    # With no data, the empty state "All caught up!" should appear
    empty = gui_page.locator("text=All caught up!")
    # Or a review card is present (difficulty/stability stats)
    stats = gui_page.locator("text=Difficulty")
    # Or the DI container is not initialized yet (loading state)
    connecting = gui_page.locator("text=Connecting")
    assert empty.count() >= 1 or stats.count() >= 1 or connecting.count() >= 1


def test_review_nav_link_present(gui_page: Page, gui_base_url: str) -> None:
    """Sidebar/bottom nav contains a link to the Review page."""
    gui_page.goto(gui_base_url)
    gui_page.wait_for_load_state("networkidle")
    review_links = gui_page.locator("a[href='/review']")
    assert review_links.count() >= 1
