"""Tests for the Settings page — pure helpers and rendering logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from sophia.gui.pages.settings import (
    format_session_age,
    health_status_label,
    hermes_setup_status,
)

# ---------------------------------------------------------------------------
# format_session_age — pure function tests
# ---------------------------------------------------------------------------


class TestFormatSessionAge:
    def test_recent_session_shows_minutes(self) -> None:
        now = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)
        created = (now - timedelta(minutes=15)).isoformat()
        result = format_session_age(created, now=now)
        assert "15" in result
        assert "minute" in result

    def test_hours_old_session(self) -> None:
        now = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)
        created = (now - timedelta(hours=3)).isoformat()
        result = format_session_age(created, now=now)
        assert "3" in result
        assert "hour" in result

    def test_days_old_session(self) -> None:
        now = datetime(2026, 3, 27, 12, 0, tzinfo=UTC)
        created = (now - timedelta(days=2, hours=5)).isoformat()
        result = format_session_age(created, now=now)
        assert "2" in result
        assert "day" in result

    def test_invalid_timestamp_returns_unknown(self) -> None:
        assert format_session_age("not-a-date") == "unknown"

    def test_defaults_to_utcnow_when_now_omitted(self) -> None:
        recent = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        result = format_session_age(recent)
        assert "minute" in result


# ---------------------------------------------------------------------------
# health_status_label — pure function tests
# ---------------------------------------------------------------------------


class TestHealthStatusLabel:
    def test_none_monitor_returns_not_connected(self) -> None:
        text, css = health_status_label(None)
        assert text == "Not connected"
        assert "red" in css

    def test_healthy_monitor_returns_connected(self) -> None:
        monitor = MagicMock()
        monitor.is_healthy = True
        text, css = health_status_label(monitor)
        assert text == "Connected"
        assert "green" in css

    def test_unhealthy_monitor_returns_session_expired(self) -> None:
        monitor = MagicMock()
        monitor.is_healthy = False
        text, css = health_status_label(monitor)
        assert text == "Session expired"
        assert "amber" in css


# ---------------------------------------------------------------------------
# get_health_monitor accessor
# ---------------------------------------------------------------------------


class TestGetHealthMonitor:
    def test_returns_module_level_monitor(self) -> None:
        from sophia.gui import app as app_module

        mock_monitor = MagicMock()
        original = getattr(app_module, "_health_monitor", None)
        try:
            app_module._health_monitor = mock_monitor  # pyright: ignore[reportPrivateUsage]
            from sophia.gui.app import get_health_monitor

            assert get_health_monitor() is mock_monitor
        finally:
            app_module._health_monitor = original  # pyright: ignore[reportPrivateUsage]

    def test_returns_none_when_no_monitor(self) -> None:
        from sophia.gui import app as app_module

        original = getattr(app_module, "_health_monitor", None)
        try:
            app_module._health_monitor = None  # pyright: ignore[reportPrivateUsage]
            from sophia.gui.app import get_health_monitor

            assert get_health_monitor() is None
        finally:
            app_module._health_monitor = original  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# hermes_setup_status — pure function tests
# ---------------------------------------------------------------------------


class TestHermesSetupStatus:
    def test_configured_when_setup_complete(self) -> None:
        label, icon, css = hermes_setup_status(is_complete=True)
        assert label == "Configured"
        assert icon == "check_circle"
        assert css == "text-green-600"

    def test_not_configured_when_setup_incomplete(self) -> None:
        label, icon, css = hermes_setup_status(is_complete=False)
        assert label == "Not configured"
        assert icon == "pending"
        assert css == "text-gray-500"


# ---------------------------------------------------------------------------
# settings_content — integration-style tests with mocked NiceGUI
# ---------------------------------------------------------------------------

_PATCH_BASE = "sophia.gui.pages.settings"


class TestSettingsContentNoContainer:
    async def test_shows_not_initialized_when_container_is_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(f"{_PATCH_BASE}.get_container", lambda: None)

        mock_label = MagicMock(side_effect=lambda text: MagicMock(classes=MagicMock()))
        monkeypatch.setattr(f"{_PATCH_BASE}.ui.label", mock_label)

        from sophia.gui.pages.settings import settings_content

        await settings_content()
        mock_label.assert_any_call("Application not initialized.")


class TestSettingsContentWithContainer:
    @pytest.fixture(autouse=True)
    def _mock_ui_containers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Mock NiceGUI layout elements that need a slot context."""
        monkeypatch.setattr(f"{_PATCH_BASE}.ui.card", MagicMock)
        monkeypatch.setattr(f"{_PATCH_BASE}.ui.row", MagicMock)
        monkeypatch.setattr(f"{_PATCH_BASE}.ui.separator", MagicMock)
        monkeypatch.setattr(
            f"{_PATCH_BASE}.ui.icon",
            lambda *a, **kw: MagicMock(classes=MagicMock()),
        )
        monkeypatch.setattr(
            f"{_PATCH_BASE}.ui.button",
            lambda *a, **kw: MagicMock(
                classes=MagicMock(return_value=MagicMock(props=MagicMock())),
            ),
        )
        monkeypatch.setattr(
            f"{_PATCH_BASE}.app.storage",
            MagicMock(user={}),
        )
        # _jobs_content is @ui.refreshable which requires a real NiceGUI slot
        monkeypatch.setattr(f"{_PATCH_BASE}._jobs_content", lambda: None)

    async def test_renders_auth_section_not_connected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_container: MagicMock,
    ) -> None:
        monkeypatch.setattr(f"{_PATCH_BASE}.get_container", lambda: mock_container)
        monkeypatch.setattr(f"{_PATCH_BASE}.get_health_monitor", lambda: None)
        monkeypatch.setattr(f"{_PATCH_BASE}.load_session", lambda _path: None)

        label_texts: list[str] = []

        def track_label(text: str) -> MagicMock:
            label_texts.append(text)
            return MagicMock(classes=MagicMock(return_value=MagicMock(style=MagicMock())))

        monkeypatch.setattr(f"{_PATCH_BASE}.ui.label", track_label)

        from sophia.gui.pages.settings import settings_content

        await settings_content()

        all_text = " ".join(label_texts)
        assert "Not connected" in all_text

    async def test_renders_auth_section_connected(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_container: MagicMock,
    ) -> None:
        monitor = MagicMock()
        monitor.is_healthy = True
        monkeypatch.setattr(f"{_PATCH_BASE}.get_container", lambda: mock_container)
        monkeypatch.setattr(f"{_PATCH_BASE}.get_health_monitor", lambda: monitor)

        creds = MagicMock()
        creds.created_at = datetime.now(UTC).isoformat()
        monkeypatch.setattr(f"{_PATCH_BASE}.load_session", lambda _path: creds)

        label_texts: list[str] = []

        def track_label(text: str) -> MagicMock:
            label_texts.append(text)
            return MagicMock(classes=MagicMock(return_value=MagicMock(style=MagicMock())))

        monkeypatch.setattr(f"{_PATCH_BASE}.ui.label", track_label)

        from sophia.gui.pages.settings import settings_content

        await settings_content()

        all_text = " ".join(label_texts)
        assert "Connected" in all_text

    async def test_renders_config_section_with_settings_values(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_container: MagicMock,
    ) -> None:
        monkeypatch.setattr(f"{_PATCH_BASE}.get_container", lambda: mock_container)
        monkeypatch.setattr(f"{_PATCH_BASE}.get_health_monitor", lambda: None)
        monkeypatch.setattr(f"{_PATCH_BASE}.load_session", lambda _path: None)

        label_texts: list[str] = []

        def track_label(text: str) -> MagicMock:
            label_texts.append(text)
            return MagicMock(classes=MagicMock(return_value=MagicMock(style=MagicMock())))

        monkeypatch.setattr(f"{_PATCH_BASE}.ui.label", track_label)

        from sophia.gui.pages.settings import settings_content

        await settings_content()

        all_text = " ".join(label_texts)
        assert str(mock_container.settings.data_dir) in all_text
        assert "300" in all_text  # keepalive interval

    async def test_renders_jobs_section_header(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_container: MagicMock,
    ) -> None:
        monkeypatch.setattr(f"{_PATCH_BASE}.get_container", lambda: mock_container)
        monkeypatch.setattr(f"{_PATCH_BASE}.get_health_monitor", lambda: None)
        monkeypatch.setattr(f"{_PATCH_BASE}.load_session", lambda _path: None)

        label_texts: list[str] = []

        def track_label(text: str) -> MagicMock:
            label_texts.append(text)
            return MagicMock(classes=MagicMock(return_value=MagicMock(style=MagicMock())))

        monkeypatch.setattr(f"{_PATCH_BASE}.ui.label", track_label)

        from sophia.gui.pages.settings import settings_content

        await settings_content()

        all_text = " ".join(label_texts)
        assert "Background Jobs" in all_text


class TestLogoutAction:
    async def test_logout_calls_clear_session(
        self,
        monkeypatch: pytest.MonkeyPatch,
        mock_container: MagicMock,
    ) -> None:
        monkeypatch.setattr(f"{_PATCH_BASE}.get_container", lambda: mock_container)

        clear_calls: list[object] = []
        monkeypatch.setattr(
            f"{_PATCH_BASE}.clear_session",
            lambda path: clear_calls.append(path),
        )

        mock_storage = MagicMock()
        monkeypatch.setattr(f"{_PATCH_BASE}.app.storage", MagicMock(user=mock_storage))
        monkeypatch.setattr(f"{_PATCH_BASE}.ui.navigate", MagicMock())
        monkeypatch.setattr(f"{_PATCH_BASE}.ui.notify", MagicMock())

        from sophia.adapters.auth import session_path
        from sophia.gui.pages.settings import perform_logout

        perform_logout(mock_container)

        expected = session_path(mock_container.settings.config_dir)
        assert len(clear_calls) == 1
        assert clear_calls[0] == expected
        mock_storage.clear.assert_called_once()
