"""Tests for the Hermes setup wizard — pure helper functions."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sophia.domain.models import WhisperModel
from sophia.gui.pages.lectures_setup import estimate_storage_mb, is_docker


class TestIsDocker:
    """Detect Docker container environment."""

    def test_true_when_dockerenv_exists(self) -> None:
        with (
            patch("sophia.gui.pages.lectures_setup.os.path.exists", return_value=True),
            patch.dict("os.environ", {}, clear=True),
        ):
            assert is_docker() is True

    def test_true_when_env_var_set(self) -> None:
        with (
            patch("sophia.gui.pages.lectures_setup.os.path.exists", return_value=False),
            patch.dict("os.environ", {"SOPHIA_DOCKER": "1"}),
        ):
            assert is_docker() is True

    def test_false_when_neither(self) -> None:
        with (
            patch("sophia.gui.pages.lectures_setup.os.path.exists", return_value=False),
            patch.dict("os.environ", {}, clear=True),
        ):
            assert is_docker() is False


class TestEstimateStorageMb:
    """Storage estimates per Whisper model size."""

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            (WhisperModel.LARGE_V3, 3500),
            (WhisperModel.TURBO, 2000),
            (WhisperModel.MEDIUM, 2000),
            (WhisperModel.SMALL, 1000),
        ],
    )
    def test_known_models(self, model: WhisperModel, expected: int) -> None:
        assert estimate_storage_mb(model) == expected
