"""E2E dashboard tests — verify dashboard loads and density toggle is present."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e


def test_dashboard_loads(gui_page: Page) -> None:
    """Dashboard page renders the heading."""
    gui_page.wait_for_load_state("networkidle")
    heading = gui_page.locator("text=Dashboard")
    assert heading.count() >= 1


def test_density_toggle_present(gui_page: Page) -> None:
    """Density mode toggle buttons are available on the dashboard."""
    gui_page.wait_for_load_state("networkidle")
    for label in ("Focus", "Standard", "Full"):
        assert gui_page.locator(f"text={label}").count() >= 1


def test_main_content_landmark(gui_page: Page) -> None:
    """The main content area has an id for skip-link targeting."""
    gui_page.wait_for_load_state("networkidle")
    main = gui_page.locator("#main-content")
    assert main.count() == 1
