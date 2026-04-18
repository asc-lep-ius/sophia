"""Error boundary component — catches exceptions in page content and shows recovery UI."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

import structlog
from nicegui import ui

if TYPE_CHECKING:
    from collections.abc import Callable

from sophia.gui.components.error_display import clear_errors, error_display
from sophia.gui.middleware.error_handler import handle_exception
from sophia.gui.services.error_service import classify_error

log = structlog.get_logger()


async def error_boundary(content_fn: Callable[[], Any], *, page_name: str = "page") -> None:
    """Render *content_fn* inside an error boundary.

    If *content_fn* raises, log the error and show a recovery card with
    full traceback and retry button. The boundary is per-page, so one broken
    page doesn't take down the whole app.
    """
    clear_errors()
    try:
        result = content_fn()
        if inspect.isawaitable(result):
            await result
    except Exception as exc:
        handle_exception(exc)
        error_display(
            exc,
            category=classify_error(exc),
            operation=page_name,
            on_retry=lambda: ui.navigate.reload(),
        )
