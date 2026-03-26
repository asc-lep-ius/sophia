"""E2E study flow tests — verify study page loads and key elements are present."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def test_study_page_loads(gui_page: Page, gui_base_url: str) -> None:
    """Study page loads without error."""
    gui_page.goto(f"{gui_base_url}/study")
    gui_page.wait_for_load_state("networkidle")
    assert gui_page.locator("text=Something went wrong").count() == 0


def test_study_heading_present(gui_page: Page, gui_base_url: str) -> None:
    """Study page renders its heading."""
    gui_page.goto(f"{gui_base_url}/study")
    gui_page.wait_for_load_state("networkidle")
    heading = gui_page.locator("text=Study Session")
    assert heading.count() >= 1


def test_study_nav_link_present(gui_page: Page, gui_base_url: str) -> None:
    """Sidebar/bottom nav contains a link to the Study page."""
    gui_page.goto(gui_base_url)
    gui_page.wait_for_load_state("networkidle")
    study_links = gui_page.locator("a[href='/study']")
    assert study_links.count() >= 1


def test_study_main_content_landmark(gui_page: Page, gui_base_url: str) -> None:
    """The #main-content landmark exists on the study page."""
    gui_page.goto(f"{gui_base_url}/study")
    gui_page.wait_for_load_state("networkidle")
    assert gui_page.locator("#main-content").count() == 1
