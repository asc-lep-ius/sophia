"""Playwright E2E test fixtures for the Sophia GUI."""

from __future__ import annotations

import os
import threading
import time
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from collections.abc import Generator

    from playwright.sync_api import Page


@pytest.fixture(scope="session")
def gui_base_url() -> Generator[str, None, None]:
    """Start the NiceGUI app in a background thread and yield its base URL."""
    import socket

    from sophia.config import Settings

    # Find a free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    # NiceGUI's ui.run() detects pytest and reads port from this env var
    os.environ["NICEGUI_SCREEN_TEST_PORT"] = str(port)

    base_url = f"http://127.0.0.1:{port}"
    settings = Settings(gui_host="127.0.0.1", gui_port=port)

    def _run_server() -> None:
        from nicegui import ui

        from sophia.gui.app import configure

        configure(settings)
        ui.run(  # type: ignore[reportUnknownMemberType]
            host="127.0.0.1",
            port=port,
            title="Sophia Test",
            reload=False,
            show=False,
            storage_secret="sophia-test-storage",
        )

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # Wait for the server to be ready
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=2)
            if resp.status_code == 200:
                break
        except httpx.ConnectError:
            time.sleep(0.5)
    else:
        msg = f"GUI server did not start within 30s on {base_url}"
        raise TimeoutError(msg)

    yield base_url


@pytest.fixture
def gui_page(page: Page, gui_base_url: str) -> Page:
    """Navigate to the GUI base URL and return the Playwright page."""
    page.goto(gui_base_url)
    return page
