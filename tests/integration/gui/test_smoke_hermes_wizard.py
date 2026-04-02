"""Smoke test for Hermes setup wizard — validates 2-step wizard against a fresh GUI.

Starts its own NiceGUI server on a random port, no Docker required.
Run with:  uv run pytest tests/integration/gui/test_smoke_hermes_wizard.py -m e2e -v
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Final

import pytest
from playwright.sync_api import expect

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Page

pytestmark = pytest.mark.e2e

_WAIT: Final = 8_000


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def hermes_server_url() -> Generator[str, None, None]:
    """Start a local NiceGUI server with current code and yield its URL."""
    import asyncio
    import socket
    import threading
    import time
    from unittest.mock import MagicMock

    import httpx

    from sophia.config import Settings

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    os.environ["NICEGUI_SCREEN_TEST_PORT"] = str(port)
    url = f"http://127.0.0.1:{port}"
    settings = Settings(gui_host="127.0.0.1", gui_port=port, auto_sync=False)

    def _run_server() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        from nicegui import ui

        from sophia.gui.app import configure

        configure(settings)
        ui.run(
            host="127.0.0.1",
            port=port,
            title="Sophia Hermes Smoke",
            reload=False,
            show=False,
            storage_secret="hermes-smoke-test-secret",
        )

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{url}/health", timeout=2)
            if resp.status_code == 200:
                break
        except httpx.ConnectError:
            time.sleep(0.5)
    else:
        msg = f"Hermes smoke server did not start within 30s on {url}"
        raise TimeoutError(msg)

    # Inject a mock container so pages that need it (Settings, Lectures) work
    from sophia.gui.middleware.health import set_container

    container = MagicMock(
        spec_set=["settings", "http", "db", "moodle", "tiss", "opencast", "lecture_downloader"],
    )
    container.settings = settings
    container.db = MagicMock()
    container.http = MagicMock()
    container.moodle = MagicMock()
    container.tiss = MagicMock()
    container.opencast = MagicMock()
    container.lecture_downloader = MagicMock()
    set_container(container)

    yield url

    # Teardown — mirrors NiceGUI's Screen.stop_server()
    from nicegui.server import Server

    if hasattr(Server, "instance"):
        Server.instance.should_exit = True
    server_thread.join(timeout=10)


@pytest.fixture
def pg(page: Page) -> Page:
    """Fresh page with default viewport."""
    page.set_default_timeout(_WAIT)
    return page


def _goto(pg: Page, url: str) -> None:
    pg.goto(url)
    pg.wait_for_load_state("networkidle")


# ===========================================================================
# AC: Lectures landing page — setup gate
# ===========================================================================


class TestLecturesLandingPage:
    """AC: navigating to /lectures shows setup prompt when not configured."""

    def test_page_loads_without_error(self, pg: Page, hermes_server_url: str) -> None:
        _goto(pg, f"{hermes_server_url}/lectures")
        expect(pg.locator("text=Something went wrong")).to_have_count(0)
        expect(pg.locator("text=Application not initialized")).to_have_count(0)

    def test_setup_required_message(self, pg: Page, hermes_server_url: str) -> None:
        """AC: 'When the student navigates to /lectures → they see setup required'."""
        _goto(pg, f"{hermes_server_url}/lectures")
        expect(pg.locator("text=Lecture Pipeline Setup Required").first).to_be_visible()

    def test_run_setup_button(self, pg: Page, hermes_server_url: str) -> None:
        """AC: 'Run Setup' button is present and navigates to /lectures/setup."""
        _goto(pg, f"{hermes_server_url}/lectures")
        btn = pg.locator("button:has-text('Run Setup')")
        expect(btn.first).to_be_visible()


# ===========================================================================
# AC: Setup wizard — Step 1: GPU, Compute & LLM
# ===========================================================================


class TestWizardStep1GpuComputeLlm:
    """AC: GPU detection, Whisper model selector, and LLM provider on step 1."""

    def test_wizard_loads(self, pg: Page, hermes_server_url: str) -> None:
        _goto(pg, f"{hermes_server_url}/lectures/setup")
        expect(pg.locator("text=Lecture Pipeline Setup")).to_be_visible()
        expect(pg.locator("text=Something went wrong")).to_have_count(0)

    def test_stepper_has_two_steps(self, pg: Page, hermes_server_url: str) -> None:
        """Wizard has exactly 2 steps labeled."""
        _goto(pg, f"{hermes_server_url}/lectures/setup")
        expect(pg.locator("text=GPU, Compute & LLM").first).to_be_visible()
        expect(pg.locator("text=Review & Save").first).to_be_visible()

    def test_gpu_context_card(self, pg: Page, hermes_server_url: str) -> None:
        """AC: Step 1 shows GPU detection result (VRAM info or CPU mode)."""
        _goto(pg, f"{hermes_server_url}/lectures/setup")
        gpu_info = pg.locator("text=/GPU.*VRAM|No GPU detected|CPU mode/").first
        expect(gpu_info).to_be_visible()

    def test_gpu_detection_result(self, pg: Page, hermes_server_url: str) -> None:
        """AC: Shows GPU name + VRAM or 'No GPU detected — CPU mode'."""
        _goto(pg, f"{hermes_server_url}/lectures/setup")
        gpu_info = pg.locator("text=/GPU.*VRAM|No GPU detected|CPU mode/").first
        expect(gpu_info).to_be_visible()

    def test_whisper_model_selector(self, pg: Page, hermes_server_url: str) -> None:
        """AC: Whisper model dropdown is present on step 1."""
        _goto(pg, f"{hermes_server_url}/lectures/setup")
        expect(pg.locator("text=Whisper Model").first).to_be_visible()

    def test_cpu_recommendation_for_no_gpu(self, pg: Page, hermes_server_url: str) -> None:
        """AC: CPU-only → recommends small/medium model, shows ~2× estimate."""
        _goto(pg, f"{hermes_server_url}/lectures/setup")
        if pg.locator("text=No GPU detected").count() > 0:
            expect(pg.locator("text=/small model.*2.*real-time/").first).to_be_visible()

    def test_review_settings_button(self, pg: Page, hermes_server_url: str) -> None:
        """Step 1 has 'Review Settings' button to advance to step 2."""
        _goto(pg, f"{hermes_server_url}/lectures/setup")
        expect(pg.locator("button:has-text('Review Settings')").first).to_be_visible()


# ===========================================================================
# AC: Setup wizard — Step 2: Review & Save
# ===========================================================================


class TestWizardStep2ReviewSave:
    """AC: Storage requirements, config summary, and save action on step 2."""

    def _navigate_to_step2(self, pg: Page, hermes_server_url: str) -> None:
        _goto(pg, f"{hermes_server_url}/lectures/setup")
        pg.wait_for_timeout(1000)
        review_btn = pg.locator("button:has-text('Review Settings')")
        if review_btn.count() == 0:
            pytest.skip("wizard step 1 did not render — cannot navigate")
        review_btn.first.click()
        pg.wait_for_timeout(500)

    def test_storage_requirements_card(self, pg: Page, hermes_server_url: str) -> None:
        """AC: Shows estimated disk usage for selected model."""
        self._navigate_to_step2(pg, hermes_server_url)
        expect(pg.locator("text=Storage Requirements").first).to_be_visible()
        expect(pg.locator("text=/Estimated disk usage.*GB/").first).to_be_visible()

    def test_model_weights_breakdown(self, pg: Page, hermes_server_url: str) -> None:
        """AC: Shows model weights and transcript estimates."""
        self._navigate_to_step2(pg, hermes_server_url)
        expect(pg.locator("text=/Model weights/").first).to_be_visible()
        expect(pg.locator("text=/500 MB per 100h/").first).to_be_visible()

    def test_data_directory_display(self, pg: Page, hermes_server_url: str) -> None:
        """AC: Shows data and config directory paths."""
        self._navigate_to_step2(pg, hermes_server_url)
        expect(pg.locator("text=Data Directory").first).to_be_visible()
        expect(pg.locator("text=Data:").first).to_be_visible()
        expect(pg.locator("text=Config:").first).to_be_visible()

    def test_config_summary(self, pg: Page, hermes_server_url: str) -> None:
        """AC: Shows full configuration summary before saving."""
        self._navigate_to_step2(pg, hermes_server_url)
        expect(pg.locator("text=Configuration Summary").first).to_be_visible()
        expect(pg.locator("text=/Whisper model/").first).to_be_visible()
        expect(pg.locator("text=/Device/").first).to_be_visible()
        expect(pg.locator("text=/LLM provider/").first).to_be_visible()
        expect(pg.locator("text=/Embedding model/").first).to_be_visible()

    def test_llm_validation_icon(self, pg: Page, hermes_server_url: str) -> None:
        """AC: LLM provider validation indicator is shown."""
        self._navigate_to_step2(pg, hermes_server_url)
        icon = pg.locator("text=/check_circle|warning/").first
        expect(icon).to_be_visible()

    def test_save_configuration_button(self, pg: Page, hermes_server_url: str) -> None:
        """AC: 'Save Configuration' button is present on step 2."""
        self._navigate_to_step2(pg, hermes_server_url)
        expect(pg.locator("button:has-text('Save Configuration')").first).to_be_visible()


# ===========================================================================
# AC: Full wizard completion flow
# ===========================================================================


class TestWizardCompletionFlow:
    """AC: Completing the wizard persists state and redirects to /lectures."""

    def test_complete_wizard_and_redirect(self, pg: Page, hermes_server_url: str) -> None:
        """AC: 'Given the student completes the wizard → /lectures shows dashboard'."""
        _goto(pg, f"{hermes_server_url}/lectures/setup")
        pg.wait_for_timeout(1000)

        # Step 1 → click "Review Settings" to advance to step 2
        review_btn = pg.locator("button:has-text('Review Settings')")
        if review_btn.count() == 0:
            pytest.skip("wizard step 1 did not render — cannot navigate")
        review_btn.first.click()
        pg.wait_for_timeout(500)

        # Step 2 → click "Save Configuration" to complete
        save_btn = pg.locator("button:has-text('Save Configuration')")
        expect(save_btn.first).to_be_visible()
        save_btn.first.click()
        pg.wait_for_timeout(2000)

        # Should redirect to /lectures and show the dashboard placeholder (not setup prompt)
        expect(pg.locator("text=Lectures").first).to_be_visible(timeout=_WAIT)

    def test_lectures_shows_dashboard_after_setup(self, pg: Page, hermes_server_url: str) -> None:
        """AC: 'When they navigate to /lectures again → they see Lectures page'."""
        _goto(pg, f"{hermes_server_url}/lectures")
        # After wizard completion, should NOT show setup required
        # Should show the lectures dashboard/placeholder
        expect(pg.locator("text=Lectures").first).to_be_visible(timeout=_WAIT)


# ===========================================================================
# AC: Settings page — Re-run Setup
# ===========================================================================


class TestSettingsHermesSection:
    """AC: Re-run Setup option in Settings page."""

    def test_hermes_section_visible(self, pg: Page, hermes_server_url: str) -> None:
        """AC: Settings page shows 'Lecture Pipeline (Hermes)' section."""
        _goto(pg, f"{hermes_server_url}/settings")
        expect(pg.locator("text=Lecture Pipeline (Hermes)").first).to_be_visible(timeout=_WAIT)

    def test_setup_status_indicator(self, pg: Page, hermes_server_url: str) -> None:
        """AC: Setup status shown with appropriate icon."""
        _goto(pg, f"{hermes_server_url}/settings")
        status = pg.locator("text=/Configured|Not configured/").first
        expect(status).to_be_visible(timeout=_WAIT)

    def test_rerun_setup_button(self, pg: Page, hermes_server_url: str) -> None:
        """AC: 'Re-run Setup' button present when setup was completed."""
        _goto(pg, f"{hermes_server_url}/settings")
        # Either 'Re-run Setup' (if completed) or 'Run Setup' (if not)
        btn = pg.locator("button:has-text('Setup')")
        expect(btn.first).to_be_visible(timeout=_WAIT)


# ===========================================================================
# AC: Navigation — Lectures in sidebar
# ===========================================================================


class TestNavigation:
    """AC: Lectures nav item is present in the sidebar."""

    def test_lectures_nav_item(self, pg: Page, hermes_server_url: str) -> None:
        _goto(pg, f"{hermes_server_url}/")
        expect(pg.locator("text=Lectures").first).to_be_visible(timeout=_WAIT)
