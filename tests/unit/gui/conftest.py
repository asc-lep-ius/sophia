"""Shared fixtures for GUI tests."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncSession

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


@contextlib.asynccontextmanager
async def _session_scope(session: object) -> AsyncIterator[object]:
    yield session


@pytest.fixture
def mock_db_session() -> AsyncMock:
    """The session ``mock_container`` hands out.

    Exposed as its own fixture because ``AppContainer`` has no attribute to
    reach it through: the real container yields sessions from a factory and
    never holds one.
    """
    return AsyncMock()


@pytest.fixture
def mock_container(mock_settings: Settings, mock_db_session: AsyncMock) -> AppContainer:
    """Fake AppContainer with mocked async resources."""
    container = MagicMock(
        spec_set=[
            "settings",
            "http",
            "engine",
            "session_factory",
            "session",
            "moodle",
            "tiss",
            "opencast",
            "lecture_downloader",
        ],
    )
    container.settings = mock_settings
    container.http = AsyncMock()
    container.engine = MagicMock()
    container.session_factory = MagicMock()
    # GUI services open a session per call; hand them one mock session so tests
    # can assert on what the service passed to the function it wraps.
    container.session = lambda **_kwargs: _session_scope(mock_db_session)
    container.moodle = MagicMock()
    container.tiss = MagicMock()
    container.opencast = MagicMock()
    container.lecture_downloader = MagicMock()
    return container


@pytest.fixture
def real_db_container(mock_settings: Settings, db: AsyncSession) -> AppContainer:
    """A container whose sessions are a real Postgres session.

    GUI wrappers that build a query themselves cannot be tested by mocking
    ``execute``: the service now hands SQLAlchemy an expression, not a string.
    """
    container = MagicMock(
        spec_set=["settings", "http", "engine", "session_factory", "session", "moodle", "tiss"],
    )
    container.settings = mock_settings
    container.http = AsyncMock()
    container.moodle = MagicMock()
    container.tiss = MagicMock()
    container.session = lambda **_kwargs: _session_scope(db)
    return container
