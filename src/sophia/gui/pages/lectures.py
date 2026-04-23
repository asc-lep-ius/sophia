"""Lectures page with granular per-lecture pipeline control."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog
from nicegui import app, background_tasks, ui

from sophia.gui.middleware.health import get_container
from sophia.gui.services.hermes_service import (
    STATUS_FILTER_ALL,
    STATUS_FILTER_INDEXED,
    STATUS_FILTER_NEEDS_PROCESSING,
    discover_lecture_modules,
    filter_episodes,
    get_lecture_modules,
    get_module_lectures,
)
from sophia.gui.services.pipeline_service import (
    EpisodeStageSelection,
    PipelineRunner,
    PipelineStage,
    PipelineState,
    StageProgress,
    StageStatus,
    estimate_storage,
)
from sophia.gui.state.storage_map import (
    TAB_LECTURES_SEARCH_QUERY,
    TAB_LECTURES_STATUS_FILTER,
    USER_HERMES_SETUP_COMPLETE,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sophia.services.hermes_manage import EpisodeStatus

log = structlog.get_logger()

_runner = PipelineRunner()

_STATUS_FILTER_OPTIONS: dict[str, str] = {
    STATUS_FILTER_ALL: "All",
    STATUS_FILTER_NEEDS_PROCESSING: "Needs Processing",
    STATUS_FILTER_INDEXED: "Fully Indexed",
}
_STAGE_LABELS: dict[PipelineStage, str] = {
    PipelineStage.DOWNLOAD: "Download",
    PipelineStage.TRANSCRIBE: "Transcribe",
    PipelineStage.INDEX: "Index",
}
_STAGE_SYMBOLS: dict[StageStatus, str] = {
    StageStatus.PENDING: "⏳",
    StageStatus.RUNNING: "🔄",
    StageStatus.COMPLETED: "✅",
    StageStatus.SKIPPED: "✅",
    StageStatus.FAILED: "❌",
    StageStatus.BLOCKED: "⚠️",
    StageStatus.CANCELLED: "⛔",
}


@dataclass(slots=True)
class StageToggleState:
    """Checkbox state for the selectable pipeline stages."""

    download: bool = True
    transcribe: bool = True
    index: bool = True


@dataclass(slots=True)
class LectureSelectionState:
    """Page-local lecture selection state."""

    selected_episode_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class LectureRecord:
    """Lecture row model for page rendering helpers."""

    module_id: int
    course_name: str
    episode: EpisodeStatus


@dataclass(frozen=True, slots=True)
class StageRenderState:
    """Prepared render data for one lecture stage row."""

    stage: PipelineStage
    label: str
    symbol: str
    status: str
    progress: float
    detail: str


def is_hermes_setup_complete() -> bool:
    """Check if Hermes setup wizard has been completed."""
    return bool(app.storage.user.get(USER_HERMES_SETUP_COMPLETE, False))


def _get_status_filter() -> str:
    try:
        value = app.storage.tab.get(TAB_LECTURES_STATUS_FILTER, STATUS_FILTER_ALL)
        return str(value) if value else STATUS_FILTER_ALL
    except RuntimeError:
        return STATUS_FILTER_ALL


def _set_status_filter(value: str) -> None:
    try:
        app.storage.tab[TAB_LECTURES_STATUS_FILTER] = value
    except RuntimeError:
        log.debug("set_status_filter_no_tab_storage")


def _get_search_query() -> str:
    try:
        value = app.storage.tab.get(TAB_LECTURES_SEARCH_QUERY, "")
        return str(value) if value else ""
    except RuntimeError:
        return ""


def _set_search_query(value: str) -> None:
    try:
        app.storage.tab[TAB_LECTURES_SEARCH_QUERY] = value
    except RuntimeError:
        log.debug("set_search_query_no_tab_storage")


def selected_stages(toggle_state: StageToggleState) -> tuple[PipelineStage, ...]:
    """Return the currently selected processing stages in execution order."""
    stages: list[PipelineStage] = []
    if toggle_state.download:
        stages.append(PipelineStage.DOWNLOAD)
    if toggle_state.transcribe:
        stages.append(PipelineStage.TRANSCRIBE)
    if toggle_state.index:
        stages.append(PipelineStage.INDEX)
    return tuple(stages)


def lecture_needs_stage(episode: EpisodeStatus, stage: PipelineStage) -> bool:
    """Return whether the episode still needs the selected stage."""
    if stage is PipelineStage.DOWNLOAD:
        return episode.download_status != "completed"
    if stage is PipelineStage.TRANSCRIBE:
        return episode.transcription_status != "completed"
    if stage is PipelineStage.INDEX:
        return episode.index_status != "completed"
    return False


def lecture_needs_selected_stages(
    episode: EpisodeStatus,
    stages: tuple[PipelineStage, ...],
) -> bool:
    """Return whether the episode still needs any selected stage."""
    return any(lecture_needs_stage(episode, stage) for stage in stages)


def select_all_unprocessed_episode_ids(
    records: list[LectureRecord],
    stages: tuple[PipelineStage, ...],
) -> set[str]:
    """Select only lectures that still need at least one selected stage."""
    if not stages:
        return set()
    return {
        record.episode.episode_id
        for record in records
        if lecture_needs_selected_stages(record.episode, stages)
    }


def course_episode_ids(records: list[LectureRecord], course_name: str) -> set[str]:
    """Return all lecture IDs for a course group."""
    return {record.episode.episode_id for record in records if record.course_name == course_name}


def build_stage_warnings(
    records_by_id: dict[str, LectureRecord],
    selected_episode_ids: set[str],
    stages: tuple[PipelineStage, ...],
) -> list[str]:
    """Build optimistic prerequisite warnings from the currently loaded lecture statuses."""
    warnings: list[str] = []
    if not stages:
        return ["Select at least one stage."] if selected_episode_ids else []

    for episode_id in sorted(selected_episode_ids):
        record = records_by_id.get(episode_id)
        if record is None:
            continue

        title = record.episode.title
        has_download = record.episode.download_status == "completed"
        has_transcript = record.episode.transcription_status == "completed"

        if PipelineStage.DOWNLOAD in stages:
            has_download = True
        if PipelineStage.TRANSCRIBE in stages:
            if not has_download:
                warnings.append(f"{title}: Transcribe requires Download.")
                continue
            has_transcript = True
        if PipelineStage.INDEX in stages and not has_transcript:
            warnings.append(f"{title}: Index requires Transcribe or an existing transcript.")

    return warnings


def build_course_tree_nodes(records: list[LectureRecord]) -> list[dict[str, object]]:
    """Create `ui.tree` nodes grouped by course with lecture leaves only."""
    courses: dict[str, list[LectureRecord]] = {}
    for record in records:
        courses.setdefault(record.course_name, []).append(record)

    nodes: list[dict[str, object]] = []
    for idx, (course_name, course_records) in enumerate(courses.items(), start=1):
        children = [
            {
                "id": _tree_episode_id(record.episode.episode_id),
                "label": _tree_label(record),
            }
            for record in course_records
        ]
        nodes.append(
            {
                "id": f"course:{idx}",
                "label": f"{course_name} ({len(children)})",
                "children": children,
            }
        )
    return nodes


def build_stage_render_states(
    episode_id: str,
    stages: tuple[PipelineStage, ...],
    pipeline_state: PipelineState,
) -> list[StageRenderState]:
    """Prepare stable render data for per-stage progress rows."""
    episode_progress = pipeline_state.episode_progress.get(episode_id)
    render_states: list[StageRenderState] = []

    for stage in stages:
        stage_progress = (
            episode_progress.stage_states.get(stage)
            if episode_progress is not None
            else StageProgress(current_stage=stage)
        )
        assert stage_progress is not None
        render_states.append(
            StageRenderState(
                stage=stage,
                label=_STAGE_LABELS[stage],
                symbol=_STAGE_SYMBOLS[stage_progress.status],
                status=stage_progress.status.value,
                progress=stage_progress.stage_progress,
                detail=stage_progress.detail,
            )
        )
    return render_states


def _tree_episode_id(episode_id: str) -> str:
    return f"episode:{episode_id}"


def _from_tree_episode_id(node_id: str) -> str | None:
    if not node_id.startswith("episode:"):
        return None
    return node_id.split(":", maxsplit=1)[1]


def _tree_label(record: LectureRecord) -> str:
    lecture_number = f"#{record.episode.lecture_number} " if record.episode.lecture_number else ""
    return f"{lecture_number}{record.episode.title}"


def _status_chip(label: str, completed: bool) -> None:
    icon = "check_circle" if completed else "schedule"
    color = "positive" if completed else "grey-6"
    ui.chip(label, icon=icon, color=color).props("dense outline")


def _render_setup_required() -> None:
    with ui.card().classes("max-w-lg mx-auto mt-8 p-6"):
        ui.label("Lecture Pipeline Setup Required").classes("text-xl font-bold mb-2")
        ui.label(
            "The lecture pipeline downloads, transcribes, and indexes your TU Wien lectures. "
            "Setup configures your transcription and embedding stack.",
        ).classes("text-gray-600 mb-3")
        ui.button(
            "Run Setup",
            on_click=lambda: ui.navigate.to("/lectures/setup"),
        ).props("color=primary")


def _render_header(on_refresh: Callable[[], None]) -> None:
    with ui.row().classes("w-full items-center gap-4 mb-4"):
        ui.label("Lectures").classes("text-2xl font-bold")
        ui.space()

        ui.input(
            placeholder="Search lectures…",
            value=_get_search_query(),
            on_change=lambda e: (_set_search_query(e.value), on_refresh()),
        ).props("outlined dense clearable").classes("w-64 hidden sm:block")

        ui.select(
            options=_STATUS_FILTER_OPTIONS,
            value=_get_status_filter(),
            on_change=lambda e: (_set_status_filter(e.value), on_refresh()),
        ).props("outlined dense").classes("w-48")

        ui.button(icon="settings", on_click=lambda: ui.navigate.to("/lectures/setup")).props(
            "flat round"
        ).tooltip("Re-run Setup")


async def lectures_content() -> None:
    """Render the Lectures page — redirects to setup if not configured."""
    container = get_container()
    if container is None:
        ui.label("Application not initialized.").classes("text-red-700")
        return

    if not is_hermes_setup_complete():
        _render_setup_required()
        return

    selection_state = LectureSelectionState()
    toggle_state = StageToggleState()

    @ui.refreshable
    async def render_dashboard() -> None:
        modules = await get_lecture_modules(container.db)
        if not modules:
            _render_empty_state(render_dashboard.refresh)
            return

        all_records: list[LectureRecord] = []
        visible_records: list[LectureRecord] = []
        status_filter = _get_status_filter()
        search_query = _get_search_query()

        for module in modules:
            episodes = await get_module_lectures(container.db, module.module_id)
            course_name = module.course_name or f"Module {module.module_id}"
            for episode in episodes:
                all_records.append(
                    LectureRecord(
                        module_id=module.module_id,
                        course_name=course_name,
                        episode=episode,
                    )
                )
            filtered = filter_episodes(
                episodes,
                status_filter=status_filter,
                search_query=search_query,
            )
            for episode in filtered:
                visible_records.append(
                    LectureRecord(
                        module_id=module.module_id,
                        course_name=course_name,
                        episode=episode,
                    )
                )

        records_by_id = {record.episode.episode_id: record for record in all_records}
        selection_state.selected_episode_ids.intersection_update(records_by_id)
        chosen_stages = selected_stages(toggle_state)
        warnings = build_stage_warnings(
            records_by_id,
            selection_state.selected_episode_ids,
            chosen_stages,
        )

        _render_selection_panel(
            container=container,
            all_records=all_records,
            visible_records=visible_records,
            records_by_id=records_by_id,
            selection_state=selection_state,
            toggle_state=toggle_state,
            warnings=warnings,
            on_refresh=render_dashboard.refresh,
        )

        if not visible_records:
            _render_no_results()

        selected_records = [
            records_by_id[episode_id]
            for episode_id in selection_state.selected_episode_ids
            if episode_id in records_by_id
        ]
        if selected_records or _runner.get_state().episode_progress:
            _render_progress_panel(
                selected_records=selected_records,
                records_by_id=records_by_id,
                chosen_stages=chosen_stages,
            )

    _render_header(render_dashboard.refresh)
    await render_dashboard()


def _render_selection_panel(
    *,
    container: object,
    all_records: list[LectureRecord],
    visible_records: list[LectureRecord],
    records_by_id: dict[str, LectureRecord],
    selection_state: LectureSelectionState,
    toggle_state: StageToggleState,
    warnings: list[str],
    on_refresh: Callable[[], None],
) -> None:
    chosen_stages = selected_stages(toggle_state)
    state = _runner.get_state()
    selected_count = len(selection_state.selected_episode_ids)

    with ui.card().classes("w-full p-4 mb-4"):
        ui.label("Batch Selection").classes("text-lg font-semibold")

        with ui.row().classes("w-full items-center gap-4 mt-2 mb-3"):
            ui.checkbox(
                "Download",
                value=toggle_state.download,
                on_change=lambda e: (
                    _setattr(toggle_state, "download", bool(e.value)),
                    on_refresh(),
                ),
            )
            ui.checkbox(
                "Transcribe",
                value=toggle_state.transcribe,
                on_change=lambda e: (
                    _setattr(toggle_state, "transcribe", bool(e.value)),
                    on_refresh(),
                ),
            )
            ui.checkbox(
                "Index",
                value=toggle_state.index,
                on_change=lambda e: (
                    _setattr(toggle_state, "index", bool(e.value)),
                    on_refresh(),
                ),
            )
            ui.space()
            ui.label(f"Selected lectures: {selected_count}").classes("text-sm text-gray-500")

        tree = ui.tree(
            build_course_tree_nodes(visible_records),
            tick_strategy="leaf",
            on_tick=lambda e: _handle_tree_tick(selection_state, e.value, on_refresh),
        ).classes("w-full")
        tree.expand()
        if selection_state.selected_episode_ids:
            tree.tick(
                [
                    _tree_episode_id(episode_id)
                    for episode_id in selection_state.selected_episode_ids
                ]
            )

        with ui.row().classes("w-full items-center gap-3 mt-4"):
            ui.button(
                "Select All Unprocessed",
                on_click=lambda: _select_all_visible(
                    tree,
                    visible_records,
                    selection_state,
                    chosen_stages,
                    on_refresh,
                ),
            ).props("outline")
            ui.button(
                "Deselect All",
                on_click=lambda: _clear_selection(tree, selection_state, on_refresh),
            ).props("outline")
            ui.space()
            ui.label(f"~{estimate_storage(selected_count):.1f} GB estimated").classes(
                "text-xs text-gray-500"
            )
            if state.running:
                if _runner.is_cancelling():
                    ui.button("Cancelling…").props("flat color=negative dense disable")
                else:
                    ui.button("Cancel", on_click=lambda: (_runner.cancel(), on_refresh())).props(
                        "flat color=negative dense"
                    )
            else:
                ui.button(
                    f"Process {selected_count or 0} Lectures",
                    on_click=lambda: background_tasks.create_lazy(
                        _start_selected_pipeline(
                            container=container,
                            records_by_id=records_by_id,
                            selection_state=selection_state,
                            chosen_stages=chosen_stages,
                            on_refresh=on_refresh,
                        ),
                        name="lectures-selective-pipeline",
                    ),
                ).props("color=primary dense")

    if warnings:
        with ui.card().classes("w-full p-3 mb-4 bg-amber-50"):
            ui.label("Pre-condition warnings").classes("font-medium text-amber-900")
            for warning in warnings[:5]:
                ui.label(warning).classes("text-sm text-amber-800")
            if len(warnings) > 5:
                ui.label(f"{len(warnings) - 5} more warning(s)…").classes("text-xs text-amber-700")


async def _start_selected_pipeline(
    *,
    container: object,
    records_by_id: dict[str, LectureRecord],
    selection_state: LectureSelectionState,
    chosen_stages: tuple[PipelineStage, ...],
    on_refresh: Callable[[], None],
) -> None:
    if _runner.get_state().running:
        ui.notify("Pipeline already running", type="warning")
        return
    if not chosen_stages:
        ui.notify("Select at least one stage", type="warning")
        return
    if not selection_state.selected_episode_ids:
        ui.notify("Select at least one lecture", type="warning")
        return

    selections = [
        EpisodeStageSelection(episode_id, chosen_stages)
        for episode_id in selection_state.selected_episode_ids
        if episode_id in records_by_id
    ]
    if not selections:
        ui.notify("No selectable lectures match the current filters", type="warning")
        return

    await asyncio.sleep(0)
    success = await _runner.run_selective_pipeline(container, selections)
    on_refresh()

    state = _runner.get_state()
    if state.cancelled:
        ui.notify("Pipeline cancelled", type="warning")
    elif success:
        ui.notify(f"Processed {state.completed_episodes} lecture(s)", type="positive")
    elif state.error:
        ui.notify(state.error, type="negative")
    else:
        ui.notify("Nothing was processed", type="warning")


def _handle_tree_tick(
    selection_state: LectureSelectionState,
    ticked_nodes: list[str] | None,
    on_refresh: Callable[[], None],
) -> None:
    selection_state.selected_episode_ids = {
        episode_id
        for node_id in (ticked_nodes or [])
        if (episode_id := _from_tree_episode_id(node_id)) is not None
    }
    on_refresh()


def _select_all_visible(
    tree: ui.tree,
    visible_records: list[LectureRecord],
    selection_state: LectureSelectionState,
    chosen_stages: tuple[PipelineStage, ...],
    on_refresh: Callable[[], None],
) -> None:
    episode_ids = select_all_unprocessed_episode_ids(visible_records, chosen_stages)
    selection_state.selected_episode_ids = episode_ids
    tree.untick()
    if episode_ids:
        tree.tick([_tree_episode_id(episode_id) for episode_id in episode_ids])
    on_refresh()


def _clear_selection(
    tree: ui.tree,
    selection_state: LectureSelectionState,
    on_refresh: Callable[[], None],
) -> None:
    selection_state.selected_episode_ids.clear()
    tree.untick()
    on_refresh()


def _render_progress_panel(
    *,
    selected_records: list[LectureRecord],
    records_by_id: dict[str, LectureRecord],
    chosen_stages: tuple[PipelineStage, ...],
) -> None:
    state = _runner.get_state()

    records_for_progress = selected_records or [
        records_by_id[episode_id]
        for episode_id in state.episode_progress
        if episode_id in records_by_id
    ]
    if not records_for_progress:
        return

    with ui.card().classes("w-full p-4 mb-4"):
        ui.label("Batch Progress").classes("text-lg font-semibold")
        ui.label().bind_text_from(state, "status_message")
        ui.linear_progress(show_value=False).bind_value_from(state, "stage_progress").props(
            "instant-feedback rounded"
        ).classes("w-full mt-2")
        ui.label().bind_text_from(
            state,
            "completed_episodes",
            backward=lambda completed: f"Completed {completed}/{state.total_episodes}",
        ).classes("text-sm text-gray-500 mt-2")
        if state.error:
            ui.label(state.error).classes("text-sm text-red-700")

    for record in records_for_progress:
        episode_progress = state.episode_progress.get(record.episode.episode_id)
        episode_stages = episode_progress.stages_to_run if episode_progress else chosen_stages
        if not episode_stages:
            continue

        caption = f"{record.course_name} · {len(episode_stages)} selected stage(s)"
        with (
            ui.expansion(record.episode.title, caption=caption)
            .classes("w-full mb-2")
            .props("default-opened")
        ):
            with ui.row().classes("w-full items-center gap-2 mb-3"):
                _status_chip("Downloaded", record.episode.download_status == "completed")
                _status_chip("Transcribed", record.episode.transcription_status == "completed")
                _status_chip("Indexed", record.episode.index_status == "completed")

            if episode_progress and episode_progress.warnings:
                for warning in episode_progress.warnings:
                    ui.label(warning).classes("text-sm text-amber-700")

            for stage in episode_stages:
                progress = (
                    episode_progress.stage_states.get(stage)
                    if episode_progress is not None
                    else StageProgress(current_stage=stage)
                )
                with ui.row().classes("w-full items-center gap-3 mb-2"):
                    ui.label().bind_text_from(
                        progress,
                        "status",
                        backward=lambda status: _STAGE_SYMBOLS[status],
                    ).classes("text-lg")
                    ui.label(_STAGE_LABELS[stage]).classes("w-24")
                    ui.linear_progress(show_value=False).bind_value_from(
                        progress,
                        "stage_progress",
                    ).props("instant-feedback rounded").classes("flex-grow")
                    ui.label().bind_text_from(
                        progress,
                        "status",
                        backward=lambda status: status.value.capitalize(),
                    ).classes("w-24 text-sm text-gray-600")
                    ui.label().bind_text_from(progress, "detail").classes(
                        "min-w-32 text-sm text-gray-500"
                    )


def _render_empty_state(on_refresh: Callable[[], None]) -> None:
    with ui.card().classes("max-w-lg mx-auto mt-8 p-6") as card:
        ui.label("No Lectures Found").classes("text-xl font-bold mb-2")
        ui.label(
            "No lectures found. Sync your courses to discover available recordings.",
        ).classes("text-gray-600 mb-4")

        async def _discover_and_process() -> None:
            container = get_container()
            if container is None:
                ui.notify("Application not initialized", type="negative")
                return
            if _runner.get_state().running:
                ui.notify("Pipeline already running", type="warning")
                return

            card.clear()
            with card:
                spinner = ui.spinner("dots", size="lg").classes("mx-auto")
                status = ui.label("Discovering lectures…").classes("text-gray-500 text-center")

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

            total_eps = sum(module.episode_count for module in modules)
            status.text = (
                f"Found {len(modules)} module(s) with {total_eps} episode(s). Starting pipeline…"
            )

            for module in modules:
                status.text = f"Processing {module.module_name}…"
                await _runner.start_batch(container, module.module_id, [])

            spinner.set_visibility(False)
            status.text = ""
            ui.notify(f"Discovered and processed {len(modules)} module(s)", type="positive")
            on_refresh()

        ui.button(
            "Sync Now",
            on_click=lambda: background_tasks.create_lazy(
                _discover_and_process(),
                name="lectures-discovery",
            ),
        ).props("color=primary")


def _render_no_results() -> None:
    ui.label("No lectures match the current filters.").classes("text-gray-500 italic mt-4")


def _setattr(target: object, name: str, value: object) -> None:
    setattr(target, name, value)
