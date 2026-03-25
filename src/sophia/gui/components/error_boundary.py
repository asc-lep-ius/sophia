"""Error boundary component — catches exceptions in page content and shows recovery UI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from nicegui import ui

if TYPE_CHECKING:
    from collections.abc import Callable

from sophia.gui.middleware.error_handler import handle_exception

log = structlog.get_logger()


def error_boundary(content_fn: Callable[[], Any], *, page_name: str = "page") -> None:
    """Render *content_fn* inside an error boundary.

    If *content_fn* raises, log the error and show a recovery card with
    Retry and Dashboard buttons. The boundary is per-page, so one broken
    page doesn't take down the whole app.
    """
    try:
        content_fn()
    except Exception as exc:
        handle_exception(exc)
        _render_error_card(exc, page_name=page_name)


def _render_error_card(exc: Exception, *, page_name: str) -> None:
    with ui.card().classes("mx-auto mt-12 p-8 max-w-md"):
        ui.icon("error_outline").classes("text-red-500 text-5xl mx-auto")
        ui.label("Something went wrong").classes("text-xl font-bold text-center mt-4")
        ui.label(f"Error on {page_name}: {type(exc).__name__}").classes(
            "text-gray-500 text-center mt-2"
        )
        with ui.row().classes("mt-6 justify-center gap-4"):
            ui.button("Retry", on_click=lambda: ui.navigate.reload()).props("outline")
            ui.button("Dashboard", on_click=lambda: ui.navigate.to("/"))
