"""Tests for the Lectures landing page — setup-complete gate logic."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from sophia.gui.pages.lectures import is_hermes_setup_complete
from sophia.gui.state.storage_map import USER_HERMES_SETUP_COMPLETE


class TestIsHermesSetupComplete:
    """Verify the boolean gate that controls setup-vs-dashboard rendering."""

    def test_returns_false_when_key_missing(self) -> None:
        mock_app = MagicMock()
        mock_app.storage.user = {}
        with patch("sophia.gui.pages.lectures.app", mock_app):
            assert is_hermes_setup_complete() is False

    def test_returns_false_when_key_is_false(self) -> None:
        mock_app = MagicMock()
        mock_app.storage.user = {USER_HERMES_SETUP_COMPLETE: False}
        with patch("sophia.gui.pages.lectures.app", mock_app):
            assert is_hermes_setup_complete() is False

    def test_returns_true_when_key_is_true(self) -> None:
        mock_app = MagicMock()
        mock_app.storage.user = {USER_HERMES_SETUP_COMPLETE: True}
        with patch("sophia.gui.pages.lectures.app", mock_app):
            assert is_hermes_setup_complete() is True
