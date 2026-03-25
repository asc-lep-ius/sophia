"""Responsive layout shell — sidebar for desktop, bottom nav for mobile."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nicegui import ui

if TYPE_CHECKING:
    from collections.abc import Callable

NAV_ITEMS: list[dict[str, str]] = [
    {"label": "Dashboard", "icon": "dashboard", "path": "/"},
    {"label": "Study", "icon": "school", "path": "/study"},
    {"label": "Review", "icon": "rate_review", "path": "/review"},
    {"label": "Search", "icon": "search", "path": "/search"},
    {"label": "Chronos", "icon": "schedule", "path": "/chronos"},
    {"label": "Calibration", "icon": "tune", "path": "/calibration"},
]


def app_shell(content_fn: Callable[[], Any]) -> None:
    """Wrap *content_fn* in a responsive app shell.

    Desktop (≥1025px): fixed left sidebar with navigation links.
    Mobile (≤768px): bottom tab bar.
    Tablet (769–1024px): collapsible sidebar.
    """
    # Desktop sidebar — hidden on small screens
    with ui.column().classes(
        "hidden lg:flex fixed left-0 top-0 h-screen w-56 bg-gray-900 text-white flex-col z-50"
    ):
        _sidebar_content()

    # Mobile bottom nav — hidden on large screens
    with ui.row().classes(
        "flex lg:hidden fixed bottom-0 left-0 right-0 bg-gray-900 text-white"
        " justify-around items-center h-16 z-50"
    ):
        _bottom_nav_content()

    # Main content area with left margin on desktop
    with ui.column().classes("lg:ml-56 min-h-screen p-4 pb-20 lg:pb-4"):
        content_fn()


def _sidebar_content() -> None:
    ui.label("Sophia").classes("text-2xl font-bold p-6 border-b border-gray-700")
    with ui.column().classes("flex-1 py-4 gap-1"):
        for item in NAV_ITEMS:
            with ui.link(target=item["path"]).classes(
                "flex items-center gap-3 px-6 py-3 hover:bg-gray-800"
                " rounded-lg mx-2 no-underline text-white"
            ):
                ui.icon(item["icon"]).classes("text-xl")
                ui.label(item["label"])


def _bottom_nav_content() -> None:
    for item in NAV_ITEMS:
        with ui.link(target=item["path"]).classes(
            "flex flex-col items-center gap-0.5 no-underline text-gray-400 hover:text-white py-1"
        ):
            ui.icon(item["icon"]).classes("text-lg")
            ui.label(item["label"]).classes("text-xs")
