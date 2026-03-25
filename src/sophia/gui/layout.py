"""Responsive layout shell — sidebar for desktop, bottom nav for mobile."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nicegui import ui

if TYPE_CHECKING:
    from collections.abc import Callable

_REDUCED_MOTION_CSS = """
<style>
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
        scroll-behavior: auto !important;
    }
}
</style>
"""

_FOCUS_RING_CSS = """
<style>
*:focus-visible {
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
}
</style>
"""

_SKIP_LINK_CSS = """
<style>
.skip-link {
    position: absolute;
    left: -9999px;
    top: auto;
    width: 1px;
    height: 1px;
    overflow: hidden;
    z-index: 9999;
}
.skip-link:focus {
    position: fixed;
    top: 0;
    left: 0;
    width: auto;
    height: auto;
    padding: 0.75rem 1.5rem;
    background: #1e3a5f;
    color: white;
    font-size: 1rem;
    z-index: 9999;
}
</style>
"""

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
    ui.add_head_html(_REDUCED_MOTION_CSS, shared=True)
    ui.add_head_html(_FOCUS_RING_CSS, shared=True)
    ui.add_head_html(_SKIP_LINK_CSS, shared=True)

    # Skip-to-content link — visible only on focus
    ui.html('<a href="#main-content" class="skip-link">Skip to content</a>')

    # Desktop sidebar — hidden on small screens
    with (
        ui.element("nav")
        .props('aria-label="Main navigation"')
        .classes(
            "hidden lg:flex fixed left-0 top-0 h-screen w-56 bg-gray-900 text-white flex-col z-50"
        )
    ):
        _sidebar_content()

    # Mobile bottom nav — hidden on large screens
    with (
        ui.element("nav")
        .props('aria-label="Mobile navigation"')
        .classes(
            "flex lg:hidden fixed bottom-0 left-0 right-0 bg-gray-900 text-white"
            " justify-around items-center h-16 z-50"
        )
    ):
        _bottom_nav_content()

    # Main content area with left margin on desktop
    with (
        ui.element("main")
        .props('id="main-content"')
        .classes("lg:ml-56 min-h-screen p-4 pb-20 lg:pb-4")
    ):
        content_fn()


def _sidebar_content() -> None:
    ui.label("Sophia").classes("text-2xl font-bold p-6 border-b border-gray-700")
    with ui.column().classes("flex-1 py-4 gap-1"):
        for item in NAV_ITEMS:
            with ui.link(target=item["path"]).classes(
                "flex items-center gap-3 px-6 py-3 hover:bg-gray-800"
                " rounded-lg mx-2 no-underline text-white"
                " focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
            ):
                ui.icon(item["icon"]).classes("text-xl")
                ui.label(item["label"])


def _bottom_nav_content() -> None:
    for item in NAV_ITEMS:
        with ui.link(target=item["path"]).classes(
            "flex flex-col items-center gap-0.5 no-underline text-gray-400 hover:text-white py-1"
            " min-h-[44px] min-w-[44px] justify-center"
            " focus:ring-2 focus:ring-blue-500 focus:ring-offset-2"
        ):
            ui.icon(item["icon"]).classes("text-lg")
            ui.label(item["label"]).classes("text-xs")
