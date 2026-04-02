"""Lectures landing page — gate to setup wizard or lecture dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from nicegui import app, ui

from sophia.gui.middleware.health import get_container
from sophia.gui.services.hermes_service import (
    STATUS_FILTER_ALL,
    STATUS_FILTER_INDEXED,
    STATUS_FILTER_NEEDS_PROCESSING,
    filter_episodes,
    get_lecture_modules,
    get_module_lectures,
    is_fully_indexed,
)
from sophia.gui.state.storage_map import (
    TAB_LECTURES_SEARCH_QUERY,
    TAB_LECTURES_STATUS_FILTER,
    USER_HERMES_SETUP_COMPLETE,
)

if TYPE_CHECKING:
    from sophia.services.hermes_manage import EpisodeStatus

log = structlog.get_logger()

# --- Filter options ----------------------------------------------------------

_STATUS_FILTER_OPTIONS: dict[str, str] = {
    STATUS_FILTER_ALL: "All",
    STATUS_FILTER_NEEDS_PROCESSING: "Needs Processing",
    STATUS_FILTER_INDEXED: "Fully Indexed",
}


# --- Public gate -------------------------------------------------------------


def is_hermes_setup_complete() -> bool:
    """Check if Hermes setup wizard has been completed."""
    return bool(app.storage.user.get(USER_HERMES_SETUP_COMPLETE, False))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


# --- Storage helpers ---------------------------------------------------------


def _get_status_filter() -> str:
    try:
        val = app.storage.tab.get(TAB_LECTURES_STATUS_FILTER, STATUS_FILTER_ALL)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        return str(val) if val else STATUS_FILTER_ALL  # pyright: ignore[reportUnknownArgumentType]
    except RuntimeError:
        return STATUS_FILTER_ALL


def _set_status_filter(value: str) -> None:
    try:
        app.storage.tab[TAB_LECTURES_STATUS_FILTER] = value  # pyright: ignore[reportUnknownMemberType]
    except RuntimeError:
        log.debug("set_status_filter_no_tab_storage")


def _get_search_query() -> str:
    try:
        val = app.storage.tab.get(TAB_LECTURES_SEARCH_QUERY, "")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        return str(val) if val else ""  # pyright: ignore[reportUnknownArgumentType]
    except RuntimeError:
        return ""


def _set_search_query(value: str) -> None:
    try:
        app.storage.tab[TAB_LECTURES_SEARCH_QUERY] = value  # pyright: ignore[reportUnknownMemberType]
    except RuntimeError:
        log.debug("set_search_query_no_tab_storage")


# --- Page entry point --------------------------------------------------------


async def lectures_content() -> None:
    """Render the Lectures page — redirects to setup if not configured."""
    container = get_container()
    if container is None:
        ui.label("Application not initialized.").classes("text-red-700")  # pyright: ignore[reportUnknownMemberType]
        return

    if not is_hermes_setup_complete():
        _render_setup_required()
        return

    _render_header()
    await _lecture_list()


# --- Setup required ----------------------------------------------------------


_PIPELINE_FEATURES = (
    "Download lecture recordings from TU Wien",
    "Transcribe audio with Whisper (GPU or CPU)",
    "Index transcripts for semantic search",
    "Generate AI-powered study questions",
)


def _render_setup_required() -> None:
    """Show info card explaining the pipeline and prompting setup."""
    with ui.card().classes("max-w-lg mx-auto mt-8 p-6"):  # pyright: ignore[reportUnknownMemberType]
        ui.label("Lecture Pipeline Setup Required").classes(  # pyright: ignore[reportUnknownMemberType]
            "text-xl font-bold mb-2",
        )
        ui.label(  # pyright: ignore[reportUnknownMemberType]
            "The lecture pipeline downloads, transcribes, and indexes your "
            "TU Wien lectures for semantic search. Setup configures your "
            "GPU, transcription model, and LLM provider.",
        ).classes("text-gray-600 mb-3")

        with ui.column().classes("gap-1 mb-3"):  # pyright: ignore[reportUnknownMemberType]
            for feature in _PIPELINE_FEATURES:
                with ui.row().classes("items-center gap-2"):  # pyright: ignore[reportUnknownMemberType]
                    ui.icon("check_circle_outline").classes("text-green-500 text-sm")  # pyright: ignore[reportUnknownMemberType]
                    ui.label(feature).classes("text-sm text-gray-600")  # pyright: ignore[reportUnknownMemberType]

        ui.label("Takes ~2 minutes.").classes("text-sm text-gray-500 mb-4 italic")  # pyright: ignore[reportUnknownMemberType]

        ui.button(  # pyright: ignore[reportUnknownMemberType]
            "Run Setup",
            on_click=lambda: ui.navigate.to("/lectures/setup"),  # pyright: ignore[reportUnknownMemberType]
        ).props("color=primary")


# --- Header (search + filter) -----------------------------------------------


def _render_header() -> None:
    """Search input + status filter dropdown."""
    with ui.row().classes("w-full items-center gap-4 mb-4"):  # pyright: ignore[reportUnknownMemberType]
        ui.label("Lectures").classes("text-2xl font-bold")  # pyright: ignore[reportUnknownMemberType]
        ui.space()  # pyright: ignore[reportUnknownMemberType]

        ui.input(  # pyright: ignore[reportUnknownMemberType]
            placeholder="Search lectures…",
            value=_get_search_query(),
            on_change=lambda e: (_set_search_query(e.value), _lecture_list.refresh()),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        ).props("outlined dense clearable").classes("w-64 hidden sm:block")  # pyright: ignore[reportUnknownMemberType]

        ui.select(  # pyright: ignore[reportUnknownMemberType]
            options=_STATUS_FILTER_OPTIONS,
            value=_get_status_filter(),
            on_change=lambda e: (_set_status_filter(e.value), _lecture_list.refresh()),  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
        ).props("outlined dense").classes("w-48")  # pyright: ignore[reportUnknownMemberType]

        ui.button(  # pyright: ignore[reportUnknownMemberType]
            icon="settings",
            on_click=lambda: ui.navigate.to("/lectures/setup"),  # pyright: ignore[reportUnknownMemberType]
        ).props("flat round").tooltip("Re-run Setup")  # pyright: ignore[reportUnknownMemberType]


# --- Lecture list (refreshable) ----------------------------------------------


@ui.refreshable
async def _lecture_list() -> None:
    """Fetch and render lectures grouped by module."""
    container = get_container()
    if not container:
        return

    db = container.db
    modules = await get_lecture_modules(db)

    if not modules:
        _render_empty_state()
        return

    status_filter = _get_status_filter()
    search_query = _get_search_query()
    any_visible = False

    for mod in modules:
        episodes = await get_module_lectures(db, mod.module_id)
        filtered = filter_episodes(episodes, status_filter=status_filter, search_query=search_query)
        if not filtered:
            continue
        any_visible = True
        _render_module_group(mod.module_id, filtered)

    if not any_visible:
        _render_no_results()


# --- Rendering helpers -------------------------------------------------------


def _render_empty_state() -> None:
    """No lectures at all — prompt the user to sync."""
    with ui.card().classes("max-w-lg mx-auto mt-8 p-6"):  # pyright: ignore[reportUnknownMemberType]
        ui.label("No Lectures Found").classes("text-xl font-bold mb-2")  # pyright: ignore[reportUnknownMemberType]
        ui.label(  # pyright: ignore[reportUnknownMemberType]
            "No lectures found. Sync your courses to discover available recordings.",
        ).classes("text-gray-600 mb-4")
        ui.button(  # pyright: ignore[reportUnknownMemberType]
            "Sync Now",
            on_click=lambda: ui.navigate.to("/lectures/setup"),  # pyright: ignore[reportUnknownMemberType]
        ).props("color=primary")


def _render_no_results() -> None:
    """Filters active but nothing matches."""
    ui.label("No lectures match the current filters.").classes(  # pyright: ignore[reportUnknownMemberType]
        "text-gray-500 italic mt-4",
    )


def _render_module_group(module_id: int, episodes: list[EpisodeStatus]) -> None:
    """Render a collapsible group of lectures for one module."""
    indexed_count = sum(1 for ep in episodes if is_fully_indexed(ep))
    with (
        ui.expansion(  # pyright: ignore[reportUnknownMemberType]
            f"Module {module_id}",
            caption=f"{len(episodes)} lectures · {indexed_count} indexed",
        )
        .classes("w-full mb-2")
        .props("default-opened")
    ):  # pyright: ignore[reportUnknownMemberType]
        for ep in episodes:
            _render_episode_card(ep)


def _render_episode_card(ep: EpisodeStatus) -> None:
    """Single lecture row with status badges."""
    with ui.card().classes("w-full p-3 mb-1"), ui.row().classes("w-full items-center gap-2"):  # pyright: ignore[reportUnknownMemberType]
        # Lecture number + title
        number_label = f"#{ep.lecture_number} " if ep.lecture_number else ""
        ui.label(f"{number_label}{ep.title}").classes(  # pyright: ignore[reportUnknownMemberType]
            "font-medium flex-grow",
        )

        # Status badges — compact on mobile (icon only), full on desktop
        _status_badge("Downloaded", ep.download_status)
        _status_badge("Transcribed", ep.transcription_status)
        _status_badge("Indexed", ep.index_status)


def _status_badge(label: str, status: str | None) -> None:
    """Render a colored chip indicating pipeline step completion."""
    completed = status == "completed"
    icon = "check_circle" if completed else "pending"
    color = "positive" if completed else "grey"

    ui.chip(  # pyright: ignore[reportUnknownMemberType]
        label,
        icon=icon,
        color=color,
    ).props("dense outline").classes(  # pyright: ignore[reportUnknownMemberType]
        "text-xs "
        # Hide label text on small screens, show icon only
        "[&_.q-chip__content]:hidden sm:[&_.q-chip__content]:inline",
    )
