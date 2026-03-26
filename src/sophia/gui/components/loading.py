"""Loading indicators — skeleton screens and progress bars."""

from __future__ import annotations

from nicegui import ui


def skeleton_card(*, count: int = 3) -> None:
    """Render placeholder skeleton cards while content loads."""
    for _ in range(count):
        with ui.card().classes("w-full p-4 animate-pulse").props('aria-label="Loading content"'):
            ui.element("div").classes("h-4 bg-gray-300 rounded w-3/4 mb-3")
            ui.element("div").classes("h-3 bg-gray-200 rounded w-1/2 mb-2")
            ui.element("div").classes("h-3 bg-gray-200 rounded w-5/6")


def loading_spinner(*, text: str = "Loading...") -> None:
    """Full-width centered spinner with optional text."""
    with (
        ui.column().classes("w-full items-center justify-center py-12").props('aria-live="polite"')
    ):
        ui.spinner("dots", size="xl").props('aria-label="Loading"')
        ui.label(text).classes("text-gray-500 mt-4")
