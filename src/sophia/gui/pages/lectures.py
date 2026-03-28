"""Lectures landing page — gate to setup wizard or lecture dashboard."""

from __future__ import annotations

from nicegui import app, ui

from sophia.gui.middleware.health import get_container
from sophia.gui.state.storage_map import USER_HERMES_SETUP_COMPLETE


def is_hermes_setup_complete() -> bool:
    """Check if Hermes setup wizard has been completed."""
    return bool(app.storage.user.get(USER_HERMES_SETUP_COMPLETE, False))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


async def lectures_content() -> None:
    """Render the Lectures page — redirects to setup if not configured."""
    container = get_container()
    if container is None:
        ui.label("Application not initialized.").classes("text-red-700")  # pyright: ignore[reportUnknownMemberType]
        return

    if not is_hermes_setup_complete():
        _render_setup_required()
        return

    _render_lectures_placeholder()


def _render_setup_required() -> None:
    """Show info card prompting user to run the setup wizard."""
    with ui.card().classes("max-w-lg mx-auto mt-8 p-6"):  # pyright: ignore[reportUnknownMemberType]
        ui.label("Lecture Pipeline Setup Required").classes(  # pyright: ignore[reportUnknownMemberType]
            "text-xl font-bold mb-2",
        )
        ui.label(  # pyright: ignore[reportUnknownMemberType]
            "The lecture pipeline needs to be configured before you can "
            "browse and search lecture content. The setup wizard will guide "
            "you through dependency checks, hardware detection, and storage "
            "configuration.",
        ).classes("text-gray-600 mb-4")
        ui.button(  # pyright: ignore[reportUnknownMemberType]
            "Run Setup",
            on_click=lambda: ui.navigate.to("/lectures/setup"),  # pyright: ignore[reportUnknownMemberType]
        ).props("color=primary")


def _render_lectures_placeholder() -> None:
    """Temporary placeholder until the full lectures dashboard is built."""
    ui.label("Lectures").classes("text-2xl font-bold mb-4")  # pyright: ignore[reportUnknownMemberType]
    ui.label("Coming soon — lectures dashboard").classes("text-gray-500")  # pyright: ignore[reportUnknownMemberType]
