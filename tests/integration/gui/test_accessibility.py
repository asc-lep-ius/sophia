"""E2E accessibility tests — axe-core WCAG 2.1 AA audit on every page."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from axe_playwright_python.sync_playwright import Axe  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

PAGES = ["/", "/study", "/review", "/search", "/chronos", "/calibration"]

_axe = Axe()


@pytest.mark.parametrize("route", PAGES)
def test_accessibility_no_violations(gui_page: Page, gui_base_url: str, route: str) -> None:
    """WCAG 2.1 AA audit reports zero violations on *route*."""
    gui_page.goto(f"{gui_base_url}{route}")
    gui_page.wait_for_load_state("networkidle")

    results = _axe.run(
        gui_page,
        options={"runOnly": ["wcag2a", "wcag2aa"]},
    )

    if results.violations_count > 0:
        report = results.generate_report()
        pytest.fail(f"WCAG 2.1 AA violations on {route}:\n{report}")
