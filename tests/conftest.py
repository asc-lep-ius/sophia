"""Shared test fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from sophia.config import Settings

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Create a Settings instance with test-safe defaults."""
    return Settings(
        data_dir=tmp_path / "data",
        download_dir=tmp_path / "downloads",
        config_dir=tmp_path / "config",
        cache_dir=tmp_path / "cache",
    )
