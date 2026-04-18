"""Global error handler and structlog bridge for the GUI."""

from __future__ import annotations

import traceback

import structlog

from sophia.gui.services.error_service import classify_error

log = structlog.get_logger()


def handle_exception(exc: Exception) -> None:
    """Log an unhandled exception via structlog with full traceback."""
    log.error(
        "unhandled_gui_error",
        error_type=type(exc).__name__,
        error_message=str(exc),
        category=classify_error(exc).value,
        traceback=traceback.format_exception(exc),
    )
