"""Tests for ErrorDisplay component — reusable error card with traceback and dedup."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from nicegui import ui
from nicegui.testing import user_simulation

from sophia.gui.components.error_display import (
    ErrorCategory,
    clear_errors,
    error_display,
)


@pytest.fixture(autouse=True)
def _reset_error_state() -> None:
    """Ensure dedup state is clean before each test."""
    clear_errors()


class TestErrorDisplay:
    async def test_renders_error_message(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                try:
                    msg = "something broke"
                    raise ValueError(msg)  # noqa: TRY301
                except Exception as exc:
                    error_display(exc, operation="test op")

            await user.open("/")
            await user.should_see("ValueError")
            await user.should_see("something broke")

    async def test_shows_traceback_in_expansion(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                try:
                    msg = "traceback test"
                    raise RuntimeError(msg)  # noqa: TRY301
                except Exception as exc:
                    error_display(exc, operation="tb op")

            await user.open("/")
            await user.should_see("Traceback")

    async def test_copy_button_present(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                try:
                    msg = "copy me"
                    raise RuntimeError(msg)  # noqa: TRY301
                except Exception as exc:
                    error_display(exc)

            await user.open("/")
            await user.should_see("Copy Error")

    async def test_dismiss_removes_card(self) -> None:
        from sophia.gui.components.error_display import _active_errors

        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                try:
                    msg = "dismiss me"
                    raise RuntimeError(msg)  # noqa: TRY301
                except Exception as exc:
                    error_display(exc)

            await user.open("/")
            await user.should_see("dismiss me")
            await user.should_see("Dismiss")
            assert len(_active_errors) == 1

    async def test_retry_button_present_when_callback_given(self) -> None:
        callback = MagicMock()

        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                try:
                    msg = "retry me"
                    raise RuntimeError(msg)  # noqa: TRY301
                except Exception as exc:
                    error_display(exc, on_retry=callback)

            await user.open("/")
            await user.should_see("Retry")

    async def test_retry_button_absent_when_no_callback(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                try:
                    msg = "no retry"
                    raise RuntimeError(msg)  # noqa: TRY301
                except Exception as exc:
                    error_display(exc)

            await user.open("/")
            await user.should_not_see("Retry")

    async def test_shows_category_label(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                try:
                    msg = "auth fail"
                    raise RuntimeError(msg)  # noqa: TRY301
                except Exception as exc:
                    error_display(exc, category=ErrorCategory.AUTH)

            await user.open("/")
            await user.should_see("AUTH")

    async def test_shows_timestamp(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                try:
                    msg = "time check"
                    raise RuntimeError(msg)  # noqa: TRY301
                except Exception as exc:
                    error_display(exc)

            await user.open("/")
            # Timestamp format includes ":" for HH:MM:SS
            await user.should_see(":")

    async def test_duplicate_errors_increment_counter(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                exc: Exception | None = None
                try:
                    msg = "dup error"
                    raise RuntimeError(msg)  # noqa: TRY301
                except Exception as e:
                    exc = e
                error_display(exc)
                error_display(exc)
                error_display(exc)

            await user.open("/")
            await user.should_see("×3")

    async def test_clear_errors_resets_state(self) -> None:
        async with user_simulation() as user:

            @ui.page("/")
            def index() -> None:
                exc: Exception | None = None
                try:
                    msg = "clearable"
                    raise RuntimeError(msg)  # noqa: TRY301
                except Exception as e:
                    exc = e
                error_display(exc)
                clear_errors()
                error_display(exc)

            await user.open("/")
            # After clear, the second display should create a new card, not increment
            await user.should_not_see("×2")
