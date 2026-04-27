"""Persistent course selector — dropdown for the layout sidebar."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from nicegui import ui

from sophia.gui.middleware.health import get_container
from sophia.gui.services.overview_service import get_course_summaries
from sophia.gui.state.course_state import (
    get_current_course,
    init_course_for_tab,
    set_current_course,
)

if TYPE_CHECKING:
    from nicegui.events import ValueChangeEventArguments

log = structlog.get_logger()


async def render_course_selector() -> None:
    """Render a compact course dropdown for the layout sidebar.

    Fetches courses from DB, renders a ``ui.select``, and binds to
    course_state.  Handles: no container, no courses, fetch errors.
    """
    await ui.context.client.connected()
    init_course_for_tab()

    container = get_container()
    if container is None:
        ui.label("Not connected").classes("text-gray-400 text-sm px-6 py-2")
        return

    try:
        summaries = await get_course_summaries(container.db)
    except Exception:
        log.exception("course_selector_fetch_failed")
        ui.label("Could not load courses").classes("text-red-400 text-sm px-6 py-2")
        return

    if not summaries:
        ui.label("No courses available").classes("text-gray-400 text-sm px-6 py-2")
        return

    options = {s.course_id: s.course_name for s in summaries}
    current = get_current_course()

    if current is not None and current not in options:
        current = None

    def on_change(e: ValueChangeEventArguments) -> None:
        if e.value is not None:
            set_current_course(e.value)

    with ui.element("div").classes("px-4 py-2"):
        ui.select(
            options=options,
            value=current,
            label="Course",
            on_change=on_change,
        ).classes("w-full").props("dense dark filled")
