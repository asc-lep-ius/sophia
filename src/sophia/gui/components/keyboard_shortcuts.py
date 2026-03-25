"""Global keyboard shortcuts — Ctrl+/ for help, Ctrl+1-4 for page navigation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from nicegui import ui

if TYPE_CHECKING:
    from nicegui.events import KeyEventArguments

_SHORTCUTS: Final[list[dict[str, str]]] = [
    {"keys": "Ctrl + /", "action": "Open keyboard shortcut help"},
    {"keys": "Ctrl + 1", "action": "Go to Dashboard"},
    {"keys": "Ctrl + 2", "action": "Go to Study"},
    {"keys": "Ctrl + 3", "action": "Go to Review"},
    {"keys": "Ctrl + 4", "action": "Go to Search"},
]

_NAV_ROUTES: Final[dict[str, str]] = {
    "1": "/",
    "2": "/study",
    "3": "/review",
    "4": "/search",
}


def register_keyboard_shortcuts() -> None:
    """Register global keyboard shortcuts for the current page."""
    dialog = _build_help_dialog()
    ui.keyboard(on_key=lambda e: _handle_global_key(e, dialog))


def _handle_global_key(e: KeyEventArguments, dialog: ui.dialog) -> None:
    if not e.action:
        return
    key = str(e.key)
    if e.modifiers.ctrl and key == "/":
        dialog.open()
    elif e.modifiers.ctrl and key in _NAV_ROUTES:
        ui.navigate.to(_NAV_ROUTES[key])


def _build_help_dialog() -> ui.dialog:
    with (
        ui.dialog() as dialog,
        ui.card().classes("p-6 min-w-[320px]").props('aria-label="Keyboard shortcuts"'),
    ):
        ui.label("Keyboard Shortcuts").classes("text-lg font-bold mb-4")
        for shortcut in _SHORTCUTS:
            with ui.row().classes("justify-between w-full py-1"):
                ui.label(shortcut["action"]).classes("text-sm")
                ui.label(shortcut["keys"]).classes(
                    "text-sm font-mono bg-gray-100 px-2 py-0.5 rounded"
                )
        ui.button("Close", on_click=dialog.close).classes("mt-4 mx-auto")
    return dialog
