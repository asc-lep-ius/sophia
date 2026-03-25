"""Shared fixtures for GUI tests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

if TYPE_CHECKING:
    from sophia.config import Settings
    from sophia.infra.di import AppContainer


@pytest.fixture
def mock_settings() -> Settings:
    """Minimal Settings instance for GUI tests (no real dirs)."""
    from sophia.config import Settings

    return Settings(
        gui_host="127.0.0.1",
        gui_port=8080,
        gui_reload=False,
    )


@pytest.fixture
def mock_container(mock_settings: Settings) -> AppContainer:
    """Fake AppContainer with mocked async resources."""
    container = MagicMock(
        spec_set=["settings", "http", "db", "moodle", "tiss", "opencast", "lecture_downloader"],
    )
    container.settings = mock_settings
    container.http = AsyncMock()
    container.db = AsyncMock()
    container.moodle = MagicMock()
    container.tiss = MagicMock()
    container.opencast = MagicMock()
    container.lecture_downloader = MagicMock()
    return container
