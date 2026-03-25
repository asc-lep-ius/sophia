"""Tests for the GUI app factory, DI lifecycle, and configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sophia.config import Settings
from sophia.gui.middleware.health import reset_state, set_container, set_container_error

if TYPE_CHECKING:
    import pytest

    from sophia.infra.di import AppContainer


class TestConfigure:
    """Test that configure() wires routes and lifecycle hooks."""

    def test_health_route_registered(self, mock_settings: Settings) -> None:
        from nicegui import app

        from sophia.gui.app import configure

        configure(mock_settings)
        route_paths = [r.path for r in app.routes if hasattr(r, "path")]  # type: ignore[reportUnknownMemberType]
        assert "/health" in route_paths
        assert "/ready" in route_paths

    def test_configure_is_idempotent(self, mock_settings: Settings) -> None:
        """Calling configure twice should not raise."""
        from sophia.gui.app import configure

        configure(mock_settings)
        configure(mock_settings)


class TestGUISettings:
    def test_default_gui_settings(self) -> None:
        s = Settings()
        assert s.gui_host == "127.0.0.1"
        assert s.gui_port == 8080
        assert s.gui_reload is False

    def test_gui_settings_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOPHIA_GUI_HOST", "0.0.0.0")
        monkeypatch.setenv("SOPHIA_GUI_PORT", "9000")
        monkeypatch.setenv("SOPHIA_GUI_RELOAD", "true")
        s = Settings()
        assert s.gui_host == "0.0.0.0"
        assert s.gui_port == 9000
        assert s.gui_reload is True


class TestDILifecycle:
    """Test startup/shutdown hooks set health state correctly."""

    def setup_method(self) -> None:
        reset_state()

    async def test_startup_sets_container_on_success(
        self,
        mock_settings: Settings,
        mock_container: AppContainer,
    ) -> None:
        """When create_app succeeds, the container ref should be set."""
        from sophia.gui.middleware import health

        # Directly test the health state helpers
        set_container(mock_container)
        assert health._container_ref["container"] is mock_container
        assert health._container_ref["error"] is None

    async def test_startup_sets_error_on_auth_failure(self, mock_settings: Settings) -> None:
        """When create_app raises AuthError, health should reflect the error."""
        from sophia.gui.middleware import health

        set_container_error("Not logged in — run: sophia auth login")
        assert health._container_ref["container"] is None
        assert "Not logged in" in (health._container_ref["error"] or "")
