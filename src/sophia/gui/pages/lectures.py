"""Lectures landing page — gate to setup wizard or lecture dashboard."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from nicegui import app, ui

from sophia.gui.middleware.health import get_container
from sophia.gui.services.hermes_service import (
    STATUS_FILTER_ALL,
    STATUS_FILTER_INDEXED,
    STATUS_FILTER_NEEDS_PROCESSING,
    discover_lecture_modules,
    filter_episodes,
    get_lecture_modules,
    get_module_lectures,
    get_unprocessed,
    is_fully_indexed,
    needs_processing,
)
from sophia.gui.services.pipeline_service import PipelineRunner, estimate_storage
from sophia.gui.state.storage_map import (
    TAB_LECTURES_SEARCH_QUERY,
    TAB_LECTURES_STATUS_FILTER,
    USER_HERMES_SETUP_COMPLETE,
)

if TYPE_CHECKING:
    from sophia.services.hermes_manage import EpisodeStatus

log = structlog.get_logger()

# --- Module-level pipeline runner (singleton per server process) --------------

_runner = PipelineRunner()

# --- Filter options ----------------------------------------------------------

_STATUS_FILTER_OPTIONS: dict[str, str] = {
    STATUS_FILTER_ALL: "All",
    STATUS_FILTER_NEEDS_PROCESSING: "Needs Processing",
    STATUS_FILTER_INDEXED: "Fully Indexed",
}


# --- Public gate -------------------------------------------------------------


def is_hermes_setup_complete() -> bool:
    """Check if Hermes setup wizard has been completed."""
    return bool(app.storage.user.get(USER_HERMES_SETUP_COMPLETE, False))


# --- Storage helpers ---------------------------------------------------------


def _get_status_filter() -> str:
    try:
        val = app.storage.tab.get(TAB_LECTURES_STATUS_FILTER, STATUS_FILTER_ALL)
        return str(val) if val else STATUS_FILTER_ALL
    except RuntimeError:
        return STATUS_FILTER_ALL


def _set_status_filter(value: str) -> None:
    try:
        app.storage.tab[TAB_LECTURES_STATUS_FILTER] = value
    except RuntimeError:
        log.debug("set_status_filter_no_tab_storage")


def _get_search_query() -> str:
    try:
        val = app.storage.tab.get(TAB_LECTURES_SEARCH_QUERY, "")
        return str(val) if val else ""
    except RuntimeError:
        return ""


def _set_search_query(value: str) -> None:
    try:
        app.storage.tab[TAB_LECTURES_SEARCH_QUERY] = value
    except RuntimeError:
        log.debug("set_search_query_no_tab_storage")


# --- Page entry point --------------------------------------------------------


async def lectures_content() -> None:
    """Render the Lectures page — redirects to setup if not configured."""
    container = get_container()
    if container is None:
        ui.label("Application not initialized.").classes("text-red-700")
        return

    if not is_hermes_setup_complete():
        _render_setup_required()
        return

    _render_header()
    await _render_batch_actions()
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
    with ui.card().classes("max-w-lg mx-auto mt-8 p-6"):
        ui.label("Lecture Pipeline Setup Required").classes(
            "text-xl font-bold mb-2",
        )
        ui.label(
            "The lecture pipeline downloads, transcribes, and indexes your "
            "TU Wien lectures for semantic search. Setup configures your "
            "GPU, transcription model, and LLM provider.",
        ).classes("text-gray-600 mb-3")

        with ui.column().classes("gap-1 mb-3"):
            for feature in _PIPELINE_FEATURES:
                with ui.row().classes("items-center gap-2"):
                    ui.icon("check_circle_outline").classes("text-green-500 text-sm")
                    ui.label(feature).classes("text-sm text-gray-600")

        ui.label("Takes ~2 minutes.").classes("text-sm text-gray-500 mb-4 italic")

        ui.button(
            "Run Setup",
            on_click=lambda: ui.navigate.to("/lectures/setup"),
        ).props("color=primary")


# --- Header (search + filter) -----------------------------------------------


def _render_header() -> None:
    """Search input + status filter dropdown."""
    with ui.row().classes("w-full items-center gap-4 mb-4"):
        ui.label("Lectures").classes("text-2xl font-bold")
        ui.space()

        ui.input(
            placeholder="Search lectures…",
            value=_get_search_query(),
            on_change=lambda e: (_set_search_query(e.value), _lecture_list.refresh()),
        ).props("outlined dense clearable").classes("w-64 hidden sm:block")

        ui.select(
            options=_STATUS_FILTER_OPTIONS,
            value=_get_status_filter(),
            on_change=lambda e: (_set_status_filter(e.value), _lecture_list.refresh()),
        ).props("outlined dense").classes("w-48")

        ui.button(
            icon="settings",
            on_click=lambda: ui.navigate.to("/lectures/setup"),
        ).props("flat round").tooltip("Re-run Setup")


# --- Batch actions -----------------------------------------------------------


async def _render_batch_actions() -> None:
    """Show batch processing bar when there are unprocessed episodes."""
    container = get_container()
    if not container:
        return

    db = container.db
    modules = await get_lecture_modules(db)
    all_episodes: list[EpisodeStatus] = []
    module_ids: list[int] = []
    for mod in modules:
        episodes = await get_module_lectures(db, mod.module_id)
        all_episodes.extend(episodes)
        module_ids.append(mod.module_id)

    unprocessed = get_unprocessed(all_episodes)
    n_unprocessed = len(unprocessed)

    if n_unprocessed == 0:
        return

    state = _runner.get_state()
    storage_gb = estimate_storage(n_unprocessed)

    with ui.row().classes("w-full items-center gap-3 mb-4 p-3 bg-blue-50 rounded"):
        if state.running:
            ui.spinner("dots", size="sm")
            progress = (
                f"{state.completed_episodes}/{state.total_episodes}"
                if state.total_episodes
                else "..."
            )
            ui.label(f"Processing {progress}…").classes("text-sm")
            if state.current_episode:
                ui.label(f"({state.current_episode})").classes("text-xs text-gray-500")
            ui.space()
            ui.button("Cancel", on_click=_runner.cancel).props("flat color=negative dense")
        else:
            ui.icon("play_circle_filled").classes("text-blue-600")
            ui.label(f"{n_unprocessed} unprocessed").classes("font-medium")
            ui.label(f"~{storage_gb:.1f} GB estimated").classes("text-xs text-gray-500")
            ui.space()

            async def _start_batch() -> None:
                if not module_ids:
                    return
                ep_ids = [ep.episode_id for ep in unprocessed]
                module_id = module_ids[0]
                if _runner.get_state().running:
                    ui.notify("Pipeline already running", type="warning")
                    return

                with ui.dialog() as confirm_dialog, ui.card().classes("p-4"):
                    ui.label("Confirm Batch Processing").classes("text-lg font-bold mb-2")
                    ui.label(
                        f"This will process {n_unprocessed} lectures and requires "
                        f"approximately {storage_gb:.1f} GB of disk space.",
                    ).classes("mb-3")
                    with ui.row().classes("justify-end gap-2"):
                        ui.button("Cancel", on_click=confirm_dialog.close).props("flat dense")

                        async def _confirmed() -> None:
                            confirm_dialog.close()
                            ui.notify(
                                f"Starting batch processing of {n_unprocessed} lectures…",
                                type="info",
                            )
                            asyncio.create_task(
                                _runner.start_batch(container, module_id, ep_ids),
                            )
                            _lecture_list.refresh()

                        ui.button("Process", on_click=_confirmed).props("color=primary dense")

                confirm_dialog.open()

            ui.button(
                f"Process {n_unprocessed} Lectures",
                on_click=_start_batch,
            ).props("color=primary dense")


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
    """No lectures — discover from Moodle/Opencast or prompt setup."""
    if not is_hermes_setup_complete():
        _render_setup_required()
        return

    with ui.card().classes("max-w-lg mx-auto mt-8 p-6") as card:
        ui.label("No Lectures Found").classes("text-xl font-bold mb-2")
        ui.label(
            "No lectures found. Sync your courses to discover available recordings.",
        ).classes("text-gray-600 mb-4")

        async def _discover_and_process() -> None:
            container = get_container()
            if not container:
                ui.notify("Application not initialized", type="negative")
                return

            if _runner.get_state().running:
                ui.notify("Pipeline already running", type="warning")
                return

            card.clear()
            with card:
                spinner = ui.spinner("dots", size="lg").classes("mx-auto")
                status = ui.label("Discovering lectures…").classes(
                    "text-gray-500 text-center",
                )

            try:
                modules = await discover_lecture_modules(container)
            except Exception:
                log.exception("lecture_discovery_failed")
                spinner.set_visibility(False)
                status.text = ""
                ui.notify("Discovery failed — check your connection", type="negative")
                return

            if not modules:
                spinner.set_visibility(False)
                status.text = "No lecture recordings found in enrolled courses."
                ui.notify("No lecture recordings found", type="warning")
                return

            total_eps = sum(m.episode_count for m in modules)
            status.text = (
                f"Found {len(modules)} module(s) with {total_eps} episode(s). Starting pipeline…"
            )

            for mod in modules:
                status.text = f"Processing {mod.module_name}…"
                try:
                    await _runner.start_batch(container, mod.module_id, [])
                except Exception:
                    log.exception("pipeline_module_failed", module_id=mod.module_id)

            spinner.set_visibility(False)
            status.text = ""
            ui.notify(
                f"Discovered and processed {len(modules)} module(s)",
                type="positive",
            )
            _lecture_list.refresh()

        ui.button("Sync Now", on_click=_discover_and_process).props("color=primary")


def _render_no_results() -> None:
    """Filters active but nothing matches."""
    ui.label("No lectures match the current filters.").classes(
        "text-gray-500 italic mt-4",
    )


def _render_module_group(module_id: int, episodes: list[EpisodeStatus]) -> None:
    """Render a collapsible group of lectures for one module."""
    indexed_count = sum(1 for ep in episodes if is_fully_indexed(ep))
    with (
        ui.expansion(
            f"Module {module_id}",
            caption=f"{len(episodes)} lectures · {indexed_count} indexed",
        )
        .classes("w-full mb-2")
        .props("default-opened")
    ):
        for ep in episodes:
            _render_episode_card(ep, module_id)


def _render_episode_card(ep: EpisodeStatus, module_id: int) -> None:
    """Single lecture row with status badges and action buttons."""
    with ui.card().classes("w-full p-3 mb-1"), ui.row().classes("w-full items-center gap-2"):
        # Lecture number + title
        number_label = f"#{ep.lecture_number} " if ep.lecture_number else ""
        ui.label(f"{number_label}{ep.title}").classes(
            "font-medium flex-grow",
        )

        # Status badges — compact on mobile (icon only), full on desktop
        _status_badge("Downloaded", ep.download_status)
        _status_badge("Transcribed", ep.transcription_status)
        _status_badge("Indexed", ep.index_status)

        # Action buttons — only show for stages that haven't completed
        if needs_processing(ep):
            _render_episode_actions(ep, module_id)


def _render_episode_actions(ep: EpisodeStatus, module_id: int) -> None:
    """Per-episode action buttons for incomplete pipeline stages."""
    container = get_container()
    state = _runner.get_state()
    is_active = state.running and state.current_episode == ep.episode_id

    if is_active:
        ui.spinner("dots", size="sm").tooltip("Processing…")
        return

    if state.running:
        return

    with ui.row().classes("gap-1"):
        if ep.download_status != "completed":
            _action_btn("download", "Download", ep, module_id, container)
        elif ep.transcription_status != "completed":
            _action_btn("mic", "Transcribe", ep, module_id, container)
        elif ep.index_status != "completed":
            _action_btn("index", "Index", ep, module_id, container)

        if needs_processing(ep):
            _action_btn("play_arrow", "Process", ep, module_id, container)


def _action_btn(
    icon: str, tooltip: str, ep: EpisodeStatus, module_id: int, container: object
) -> None:
    """Small icon button that triggers the module pipeline from one episode.

    Each pipeline stage internally skips already-completed episodes, so this
    effectively processes all pending work in the module.
    """

    async def _on_click() -> None:
        if _runner.get_state().running:
            ui.notify("Pipeline already running", type="warning")
            return
        ui.notify(f"{tooltip}: {ep.title}", type="info")
        asyncio.create_task(
            _runner.start_single(container, module_id, ep.episode_id),  # type: ignore[arg-type]
        )
        _lecture_list.refresh()

    ui.button(icon=icon, on_click=_on_click).props("flat round dense size=sm").tooltip(tooltip)


def _status_badge(label: str, status: str | None) -> None:
    """Render a colored chip indicating pipeline step completion."""
    completed = status == "completed"
    icon = "check_circle" if completed else "pending"
    color = "positive" if completed else "grey"

    ui.chip(
        label,
        icon=icon,
        color=color,
    ).props("dense outline").classes(
        "text-xs "
        # Hide label text on small screens, show icon only
        "[&_.q-chip__content]:hidden sm:[&_.q-chip__content]:inline",
    )
