"""Hermes search page — lecture transcript search with Bloom's retrieval prompts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog
from nicegui import app, ui

from sophia.gui.services.search_service import search_lectures
from sophia.gui.state.storage_map import (
    GENERAL_APP_CONTAINER,
    TAB_SEARCH_BLOOM_LEVEL,
    TAB_SEARCH_BLOOM_RESPONSE,
    TAB_SEARCH_COURSE_FILTER,
    TAB_SEARCH_QUERY,
    TAB_SEARCH_RESULTS,
    TAB_SEARCH_SELECTED_INDEX,
    USER_CURRENT_COURSE,
)

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# --- Constants ---------------------------------------------------------------

_CHUNK_PREVIEW_LENGTH: Final = 200
_DEBOUNCE_SECONDS: Final = 0.5
_DEFAULT_RESULT_COUNT: Final = 5

_BLOOM_PROMPTS: Final[list[str]] = [
    "List the three key definitions from this passage.",
    "In your own words, what did this passage explain?",
    "Give a concrete example where this concept applies.",
    "How does this passage relate to what you studied previously?",
    "What assumptions does this explanation rely on? Which might break?",
    "Write a question about this passage that would test deep understanding.",
]

_SCORE_COLORS: Final[dict[str, str]] = {
    "high": "green",
    "medium": "orange",
    "low": "red",
}


# --- Pure helpers ------------------------------------------------------------


def format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS or MM:SS (if < 1 hour)."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _next_bloom_level(current: int) -> int:
    """Advance Bloom's taxonomy level, wrapping at 6 → 0."""
    return (current + 1) % len(_BLOOM_PROMPTS)


def _score_color(score: float) -> str:
    if score >= 0.7:
        return _SCORE_COLORS["high"]
    if score >= 0.4:
        return _SCORE_COLORS["medium"]
    return _SCORE_COLORS["low"]


# --- Storage helpers ---------------------------------------------------------


def _get_query() -> str:
    return app.storage.tab.get(TAB_SEARCH_QUERY, "")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _set_query(value: str) -> None:
    app.storage.tab[TAB_SEARCH_QUERY] = value  # pyright: ignore[reportUnknownMemberType]


def _get_results() -> list[dict[str, object]]:
    return app.storage.tab.get(TAB_SEARCH_RESULTS, [])  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _set_results(results: list[dict[str, object]]) -> None:
    app.storage.tab[TAB_SEARCH_RESULTS] = results  # pyright: ignore[reportUnknownMemberType]


def _get_selected_index() -> int | None:
    return app.storage.tab.get(TAB_SEARCH_SELECTED_INDEX)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _set_selected_index(idx: int | None) -> None:
    app.storage.tab[TAB_SEARCH_SELECTED_INDEX] = idx  # pyright: ignore[reportUnknownMemberType]


def _get_bloom_level() -> int:
    return app.storage.tab.get(TAB_SEARCH_BLOOM_LEVEL, 0)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _set_bloom_level(level: int) -> None:
    app.storage.tab[TAB_SEARCH_BLOOM_LEVEL] = level  # pyright: ignore[reportUnknownMemberType]


def _get_bloom_response() -> str:
    return app.storage.tab.get(TAB_SEARCH_BLOOM_RESPONSE, "")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _set_bloom_response(text: str) -> None:
    app.storage.tab[TAB_SEARCH_BLOOM_RESPONSE] = text  # pyright: ignore[reportUnknownMemberType]


def _get_course_filter() -> str:  # pyright: ignore[reportUnusedFunction]
    return app.storage.tab.get(TAB_SEARCH_COURSE_FILTER, "")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _set_course_filter(value: str) -> None:  # pyright: ignore[reportUnusedFunction]
    app.storage.tab[TAB_SEARCH_COURSE_FILTER] = value  # pyright: ignore[reportUnknownMemberType]


# --- UI components -----------------------------------------------------------


def search_content() -> None:
    """Public entry point — renders the Hermes search page."""
    container: AppContainer | None = app.storage.general.get(GENERAL_APP_CONTAINER)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportAssignmentType]
    if container is None:
        ui.label("Application not initialized.").classes("text-red-700")
        return

    course_id: int | None = app.storage.user.get(USER_CURRENT_COURSE)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportAssignmentType]
    if course_id is None:
        ui.label("Select a course from the Dashboard to begin.").classes("text-gray-500")
        return

    _render_header(container, course_id)  # pyright: ignore[reportUnknownArgumentType]
    _search_results()


def _render_header(container: AppContainer, course_id: int) -> None:
    """Search input bar with course filter."""
    with ui.row().classes("w-full items-center gap-4 mb-4"):
        search_input = (
            ui.input(
                label="Search lecture content",
                placeholder="Enter a search query…",
                value=_get_query(),
            )
            .classes("flex-grow")
            .props('aria-label="Search lecture transcripts"')
        )

        async def _on_search(e: object) -> None:
            query = search_input.value or ""
            _set_query(query)
            if not query.strip():
                _set_results([])
                _set_selected_index(None)
                _search_results.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]
                return
            await _execute_search(container, course_id, query)

        search_input.on("keydown.enter", _on_search)

        ui.button(icon="search", on_click=_on_search).props("flat dense")


async def _execute_search(container: AppContainer, course_id: int, query: str) -> None:
    """Run the search and refresh results."""
    results = await search_lectures(container, course_id, query)  # pyright: ignore[reportUnknownArgumentType]
    serialized = [
        {
            "episode_id": r.episode_id,
            "title": r.title,
            "chunk_text": r.chunk_text,
            "start_time": r.start_time,
            "end_time": r.end_time,
            "score": r.score,
            "source": r.source,
        }
        for r in results
    ]
    _set_results(serialized)  # pyright: ignore[reportArgumentType]
    _set_selected_index(None)
    _set_bloom_response("")
    _search_results.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]


@ui.refreshable
def _search_results() -> None:
    """Render search result cards or empty state."""
    results = _get_results()
    query = _get_query()
    selected = _get_selected_index()

    # Aria-live region announces result count to screen readers
    if query.strip():
        count = len(results)
        status = (
            f"{count} result{'s' if count != 1 else ''} found" if results else "No results found"
        )
        ui.label(status).classes("sr-only").props('aria-live="polite"')

    if not query.strip():
        ui.label("Enter a search query to find lecture content.").classes(
            "text-gray-500 mt-8 text-center w-full"
        )
        return

    if not results:
        ui.label("No results found.").classes("text-gray-500 mt-8 text-center w-full")
        return

    bloom_pending = selected is not None and not _get_bloom_response().strip()

    with ui.column().classes("w-full gap-3 mt-2"):
        for idx, result in enumerate(results):
            is_selected = idx == selected
            is_disabled = bloom_pending and not is_selected
            _render_result_card(idx, result, is_selected=is_selected, disabled=is_disabled)

        if selected is not None and 0 <= selected < len(results):
            _render_result_detail(results[selected])
            _render_bloom_prompt()


def _render_result_card(
    idx: int,
    result: dict[str, object],
    *,
    is_selected: bool,
    disabled: bool,
) -> None:
    """Single result card — title, score, timestamp, preview."""
    title = str(result.get("title", "Untitled"))
    score = float(result.get("score", 0.0))  # pyright: ignore[reportArgumentType]
    start = float(result.get("start_time", 0.0))  # pyright: ignore[reportArgumentType]
    end = float(result.get("end_time", 0.0))  # pyright: ignore[reportArgumentType]
    chunk = str(result.get("chunk_text", ""))
    preview = chunk[:_CHUNK_PREVIEW_LENGTH] + ("…" if len(chunk) > _CHUNK_PREVIEW_LENGTH else "")

    card_classes = "w-full cursor-pointer" + (" ring-2 ring-blue-400" if is_selected else "")
    if disabled:
        card_classes += " opacity-50 pointer-events-none"

    with (
        ui.card()
        .classes(card_classes)
        .on(
            "click",
            lambda _, i=idx: _select_result(i),  # type: ignore[misc]
        )
    ):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(title).classes("font-semibold text-lg")
            ui.badge(f"{score:.0%}", color=_score_color(score)).classes("text-xs")

        with ui.row().classes("text-sm text-gray-500 gap-2"):
            ui.label(f"{format_timestamp(start)} – {format_timestamp(end)}")
            source = str(result.get("source", ""))
            if source:
                ui.badge(source, color="gray").classes("text-xs")

        ui.label(preview).classes("text-sm text-gray-600 mt-1")


def _select_result(idx: int) -> None:
    """Select a result card — only if no Bloom response is pending."""
    if _get_selected_index() is not None and not _get_bloom_response().strip():
        # Cannot switch while Bloom prompt is unanswered
        return
    _set_selected_index(idx)
    _set_bloom_response("")
    _search_results.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]


def _render_result_detail(result: dict[str, object]) -> None:
    """Expanded view of the selected result with full chunk text."""
    chunk_text = str(result.get("chunk_text", ""))
    title = str(result.get("title", "Untitled"))
    start = float(result.get("start_time", 0.0))  # pyright: ignore[reportArgumentType]
    end = float(result.get("end_time", 0.0))  # pyright: ignore[reportArgumentType]

    with ui.card().classes("w-full mt-4 bg-blue-50"):
        ui.label(title).classes("font-bold text-xl mb-2")
        ui.label(f"{format_timestamp(start)} – {format_timestamp(end)}").classes(
            "text-sm text-gray-500 mb-3"
        )
        ui.markdown(chunk_text).classes("prose max-w-none")


def _render_bloom_prompt() -> None:
    """Bloom's taxonomy retrieval prompt — mandatory before viewing next result."""
    level = _get_bloom_level()
    prompt = _BLOOM_PROMPTS[level]
    response = _get_bloom_response()

    with ui.card().classes("w-full mt-4 bg-amber-50 border-l-4 border-amber-400"):
        ui.label("Retrieval Practice").classes("font-bold text-lg mb-1")
        ui.label(prompt).classes("text-sm mb-3 italic")

        response_input = ui.textarea(
            label="Your response",
            value=response,
            placeholder="Type your answer here…",
        ).classes("w-full")

        def _on_response_change(e: object) -> None:
            _set_bloom_response(response_input.value or "")

        response_input.on("change", _on_response_change)

        def _submit_response() -> None:
            current = response_input.value or ""
            if not current.strip():
                ui.notify("Please provide a response before continuing.", type="warning")
                return
            _set_bloom_response(current)
            _set_bloom_level(_next_bloom_level(level))
            _set_selected_index(None)
            _search_results.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

        ui.button("Submit & Continue", on_click=_submit_response).classes("mt-2").props(
            "color=amber"
        )
