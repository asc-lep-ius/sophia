"""Tests for GUI error service — classify_error and gui_error_handler."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from sophia.domain.errors import (
    AuthError,
    HermesError,
    NetworkError,
    SophiaError,
)
from sophia.gui.components.error_display import ErrorCategory
from sophia.gui.services.error_service import (
    classify_error,
    gui_error_handler,
)

# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------


class TestClassifyError:
    def test_auth_error_maps_to_auth(self) -> None:
        assert classify_error(AuthError("bad token")) == ErrorCategory.AUTH

    def test_network_error_maps_to_network(self) -> None:
        assert classify_error(NetworkError("timeout")) == ErrorCategory.NETWORK

    def test_os_error_maps_to_storage(self) -> None:
        assert classify_error(OSError("disk full")) == ErrorCategory.STORAGE

    def test_permission_error_maps_to_storage(self) -> None:
        assert classify_error(PermissionError("denied")) == ErrorCategory.STORAGE

    def test_sophia_error_maps_to_domain(self) -> None:
        assert classify_error(SophiaError("generic")) == ErrorCategory.DOMAIN

    def test_hermes_error_maps_to_domain(self) -> None:
        assert classify_error(HermesError("pipeline")) == ErrorCategory.DOMAIN

    def test_value_error_maps_to_unknown(self) -> None:
        assert classify_error(ValueError("bad value")) == ErrorCategory.UNKNOWN

    def test_runtime_error_maps_to_unknown(self) -> None:
        assert classify_error(RuntimeError("oops")) == ErrorCategory.UNKNOWN


# ---------------------------------------------------------------------------
# gui_error_handler
# ---------------------------------------------------------------------------


class TestGuiErrorHandler:
    @pytest.mark.asyncio
    async def test_returns_result_on_success(self) -> None:
        @gui_error_handler(operation="fetch_items", fallback=[])
        async def fetch_items() -> list[int]:
            return [1, 2, 3]

        result = await fetch_items()
        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_catches_exception_returns_fallback(self) -> None:
        @gui_error_handler(operation="boom_op", fallback=42)
        async def boom_op() -> int:
            raise ValueError("kaboom")

        result = await boom_op()
        assert result == 42

    @pytest.mark.asyncio
    async def test_logs_via_structlog(self) -> None:
        @gui_error_handler(operation="log_test", fallback=None)
        async def log_test(course_id: int = 0) -> None:
            raise SophiaError("test error")

        with patch("sophia.gui.services.error_service.log") as mock_log:
            await log_test(course_id=7)

        mock_log.exception.assert_called_once()
        call_kwargs = mock_log.exception.call_args
        assert "log_test_failed" in call_kwargs.args or call_kwargs.args[0] == "log_test_failed"
        assert call_kwargs.kwargs["error_type"] == "SophiaError"
        assert call_kwargs.kwargs["error_message"] == "test error"
        assert call_kwargs.kwargs["category"] == ErrorCategory.DOMAIN

    @pytest.mark.asyncio
    async def test_shows_toast_notification(self) -> None:
        @gui_error_handler(operation="toast_op", fallback=None)
        async def toast_op() -> None:
            raise ValueError("visible error")

        with patch("sophia.gui.services.error_service.ui") as mock_ui:
            await toast_op()

        mock_ui.notify.assert_called_once()
        args = mock_ui.notify.call_args
        assert "toast_op" in args.args[0] or "toast_op" in str(args)
        assert args.kwargs.get("type") == "negative" or "negative" in str(args)

    def test_works_with_sync_functions(self) -> None:
        @gui_error_handler(operation="sync_op", fallback="default")
        def sync_op() -> str:
            raise RuntimeError("sync fail")

        result = sync_op()
        assert result == "default"

    @pytest.mark.asyncio
    async def test_toast_failure_does_not_propagate(self) -> None:
        @gui_error_handler(operation="no_ctx", fallback=-1)
        async def no_ctx() -> int:
            raise ValueError("inner")

        with patch(
            "sophia.gui.services.error_service.ui",
            new_callable=MagicMock,
        ) as mock_ui:
            mock_ui.notify.side_effect = RuntimeError("no NiceGUI context")
            result = await no_ctx()

        assert result == -1
