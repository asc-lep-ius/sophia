"""Hermes setup wizard — guided 4-step configuration for the lecture pipeline."""

from __future__ import annotations

import os

import structlog
from nicegui import app, ui

from sophia.domain.models import WhisperModel
from sophia.gui.middleware.health import get_container
from sophia.gui.state.storage_map import USER_HERMES_SETUP_COMPLETE

log = structlog.get_logger()

# Storage estimates (MB): model weight + ~500 MB for transcripts/embeddings per 100h
_MODEL_STORAGE_MB: dict[WhisperModel, int] = {
    WhisperModel.LARGE_V3: 3500,
    WhisperModel.TURBO: 2000,
    WhisperModel.MEDIUM: 2000,
    WhisperModel.SMALL: 1000,
}


def is_docker() -> bool:
    """Detect if running inside a Docker container."""
    return os.path.exists("/.dockerenv") or os.environ.get("SOPHIA_DOCKER") == "1"


def estimate_storage_mb(model: WhisperModel) -> int:
    """Estimated disk usage in MB for a given Whisper model size."""
    return _MODEL_STORAGE_MB.get(model, 2000)


async def lectures_setup_content() -> None:
    """Render the 4-step Hermes setup wizard."""
    container = get_container()
    if container is None:
        ui.label("Application not initialized.").classes("text-red-700")  # pyright: ignore[reportUnknownMemberType]
        return

    ui.label("Lecture Pipeline Setup").classes("text-2xl font-bold mb-4")  # pyright: ignore[reportUnknownMemberType]

    with ui.stepper().props("header-nav=false").classes("w-full") as stepper:  # pyright: ignore[reportUnknownMemberType]
        with ui.step("Dependencies"):  # pyright: ignore[reportUnknownMemberType]
            ui.label("Checking Hermes dependencies...")  # pyright: ignore[reportUnknownMemberType]
            with ui.row():  # pyright: ignore[reportUnknownMemberType]
                ui.button("Next", on_click=stepper.next)  # pyright: ignore[reportUnknownMemberType]

        with ui.step("GPU & Compute"):  # pyright: ignore[reportUnknownMemberType]
            ui.label("Detecting hardware configuration...")  # pyright: ignore[reportUnknownMemberType]
            with ui.row().classes("gap-2"):  # pyright: ignore[reportUnknownMemberType]
                ui.button("Back", on_click=stepper.previous)  # pyright: ignore[reportUnknownMemberType]
                ui.button("Next", on_click=stepper.next)  # pyright: ignore[reportUnknownMemberType]

        with ui.step("Storage"):  # pyright: ignore[reportUnknownMemberType]
            ui.label("Reviewing storage requirements...")  # pyright: ignore[reportUnknownMemberType]
            with ui.row().classes("gap-2"):  # pyright: ignore[reportUnknownMemberType]
                ui.button("Back", on_click=stepper.previous)  # pyright: ignore[reportUnknownMemberType]
                ui.button("Next", on_click=stepper.next)  # pyright: ignore[reportUnknownMemberType]

        with ui.step("Save & Complete"):  # pyright: ignore[reportUnknownMemberType]
            ui.label("Ready to save configuration")  # pyright: ignore[reportUnknownMemberType]
            with ui.row().classes("gap-2"):  # pyright: ignore[reportUnknownMemberType]
                ui.button("Back", on_click=stepper.previous)  # pyright: ignore[reportUnknownMemberType]
                ui.button("Complete Setup", on_click=lambda: _complete_setup())  # pyright: ignore[reportUnknownMemberType]


def _complete_setup() -> None:
    """Mark setup as complete and redirect."""
    app.storage.user[USER_HERMES_SETUP_COMPLETE] = True  # pyright: ignore[reportUnknownMemberType]
    ui.notify("Setup complete!", type="positive")  # pyright: ignore[reportUnknownMemberType]
    ui.navigate.to("/lectures")  # pyright: ignore[reportUnknownMemberType]
