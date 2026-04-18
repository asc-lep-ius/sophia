"""ErrorDisplay component — renders error cards with full traceback and deduplication."""

from __future__ import annotations

import hashlib
import traceback
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

import structlog
from nicegui import ui

if TYPE_CHECKING:
    from collections.abc import Callable

log = structlog.get_logger()


class ErrorCategory(Enum):
    """Broad classification for surfaced errors."""

    AUTH = "AUTH"
    NETWORK = "NETWORK"
    STORAGE = "STORAGE"
    DOMAIN = "DOMAIN"
    UNKNOWN = "UNKNOWN"


# module-level dedup state: hash → (count, card_element, badge_label)
_active_errors: dict[str, tuple[int, ui.card, ui.label]] = {}


def clear_errors() -> None:
    """Reset deduplication state — call on page navigation."""
    _active_errors.clear()


def error_display(
    exc: Exception,
    *,
    category: ErrorCategory = ErrorCategory.UNKNOWN,
    operation: str = "",
    on_retry: Callable[[], Any] | None = None,
    container: ui.element | None = None,
) -> None:
    """Render an error card with traceback, copy, dismiss, and optional retry.

    Deduplicates by traceback hash — repeated identical errors increment a
    counter badge instead of spawning new cards.
    """
    tb_str = "".join(traceback.format_exception(exc))
    tb_hash = hashlib.md5(tb_str.encode()).hexdigest()  # noqa: S324

    if tb_hash in _active_errors:
        count, _card, badge = _active_errors[tb_hash]
        new_count = count + 1
        badge.set_text(f"×{new_count}")
        _active_errors[tb_hash] = (new_count, _card, badge)
        return

    timestamp = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    short_msg = f"{type(exc).__name__}: {exc}"
    op_ctx = f" during {operation}" if operation else ""

    log.error(
        "error_displayed",
        error_type=type(exc).__name__,
        error_message=str(exc),
        category=category.value,
        operation=operation,
    )

    parent = container or ui.element("div")

    with parent:
        card = ui.card().classes("mx-auto mt-4 p-6 max-w-lg border-l-4 border-red-500")
        card.props('role="alert" aria-live="assertive"')

        with card:
            with ui.row().classes("items-center gap-2"):
                ui.icon("error_outline").classes("text-red-500 text-3xl")
                ui.label(short_msg).classes("text-lg font-semibold")

            with ui.row().classes("mt-1 gap-4 text-sm text-gray-500"):
                ui.label(timestamp)
                ui.label(category.value).classes("font-mono")

            badge = ui.label("×1").classes("text-xs text-gray-400")

            with ui.expansion("Traceback").classes("mt-2 w-full"):
                ui.code(tb_str).classes("text-xs w-full overflow-auto")

            copy_text = f"{short_msg}{op_ctx}\n{timestamp}\nCategory: {category.value}\n\n{tb_str}"

            with ui.row().classes("mt-4 justify-end gap-2"):
                ui.button(
                    "Copy Error",
                    on_click=lambda: ui.run_javascript(
                        f"navigator.clipboard.writeText({_js_string(copy_text)})"
                    ),
                ).props("outline color=grey size=sm")

                if on_retry is not None:
                    ui.button("Retry", on_click=on_retry).props("outline color=primary size=sm")

                ui.button(
                    "Dismiss",
                    on_click=lambda bound_card=card, bound_hash=tb_hash: _dismiss(
                        bound_card, bound_hash
                    ),
                ).props("outline color=red size=sm")

    _active_errors[tb_hash] = (1, card, badge)

    ui.notify(short_msg, type="negative", position="top-right", close_button=True)


def _dismiss(card: ui.card, tb_hash: str) -> None:
    """Remove card from UI and dedup registry."""
    card.delete()
    _active_errors.pop(tb_hash, None)


def _js_string(text: str) -> str:
    """Escape text for safe embedding in a JS string literal."""
    escaped = text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
    return f"`{escaped}`"
