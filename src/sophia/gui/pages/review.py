"""Review page — FSRS spaced repetition review session."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from nicegui import app, ui

from sophia.gui.components.loading import loading_spinner, skeleton_card
from sophia.gui.components.review_card import review_card
from sophia.gui.middleware.health import get_container
from sophia.gui.services.review_service import (
    complete_review_item,
    compute_interval_previews,
    get_due_review_items,
    rating_to_score,
)
from sophia.gui.state.storage_map import (
    TAB_REVIEW_INDEX,
    TAB_REVIEW_RECALL_TEXT,
    TAB_REVIEW_SCORES,
    TAB_REVIEW_SHOW_BACK,
)

if TYPE_CHECKING:
    from nicegui.events import KeyEventArguments

    from sophia.domain.models import ReviewSchedule

log = structlog.get_logger()

# Visual thresholds
_STABILITY_MAX_DAYS = 365


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _format_retention(difficulty: float) -> str:
    """Estimated retention as a percentage string (lower difficulty → higher retention)."""
    return f"{(1 - difficulty) * 100:.0f}%"


def _clamp_stability_pct(stability: float) -> float:
    """Stability as 0–100 percentage, clamped to [0, _STABILITY_MAX_DAYS] days."""
    return min(stability / _STABILITY_MAX_DAYS, 1.0) * 100


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def review_content() -> None:
    """Main review page entry point — called by app_shell + error_boundary."""
    _render_header()

    container = get_container()
    if not container:
        ui.label("Application not initialized.").classes("text-red-700")
        return

    await _review_session()


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------


def _render_header() -> None:
    with ui.row().classes("w-full items-center justify-between mb-4"):
        ui.label("Review").classes("text-2xl font-bold")


def _render_empty_state() -> None:
    """No reviews due — friendly empty state."""
    with ui.column().classes("w-full items-center justify-center py-16"):
        ui.icon("check_circle", color="green").classes("text-6xl")
        ui.label("All caught up!").classes("text-2xl font-bold mt-4")
        ui.label("No reviews are due right now.").classes("text-gray-500 mt-2")
        ui.link("Dashboard", "/").classes("mt-4")


def _render_card_stats(*, difficulty: float, stability: float) -> None:
    """Visual progress bars for card difficulty and stability."""
    retention = _format_retention(difficulty)
    stability_pct = _clamp_stability_pct(stability)
    difficulty_pct = difficulty * 100

    diff_color = "red" if difficulty > 0.6 else "orange" if difficulty > 0.3 else "green"

    with (
        ui.card().classes("w-full max-w-lg mx-auto p-4 mb-2"),
        ui.row().classes("w-full items-center gap-4"),
    ):
        # Difficulty bar
        with ui.column().classes("flex-1"):
            ui.label("Difficulty").classes("text-xs text-gray-500")
            ui.linear_progress(value=difficulty_pct / 100).props(f"color={diff_color}")

        # Stability bar
        with ui.column().classes("flex-1"):
            ui.label("Stability").classes("text-xs text-gray-500")
            ui.linear_progress(value=stability_pct / 100).props("color=blue")

        # Retention
        with ui.column().classes("items-center"):
            ui.label("Retention").classes("text-xs text-gray-500")
            ui.label(retention).classes("text-lg font-bold")


def _render_progress_label(current: int, total: int) -> None:
    """Show 'N of M reviews remaining' above the card."""
    remaining = total - current
    ui.label(f"{remaining} of {total} reviews remaining").classes(
        "text-sm text-gray-500 text-center w-full mb-2"
    )


def _render_session_summary(*, total: int, scores: list[float]) -> None:
    """End-of-session summary with total, average score, and dashboard link."""
    avg = sum(scores) / len(scores) if scores else 0.0

    with ui.column().classes("w-full items-center justify-center py-12"):
        ui.icon("emoji_events", color="amber").classes("text-6xl")
        ui.label("Session Complete").classes("text-2xl font-bold mt-4")

        with ui.card().classes("max-w-sm p-6 mt-4"):
            with ui.row().classes("w-full justify-between"):
                ui.label("Cards reviewed").classes("text-gray-500")
                ui.label(str(total)).classes("font-bold")
            with ui.row().classes("w-full justify-between mt-2"):
                ui.label("Average score").classes("text-gray-500")
                ui.label(f"{avg:.0%}").classes("font-bold")

        ui.link("Dashboard", "/").classes("mt-6")


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def _get_review_index() -> int:
    return app.storage.tab.get(TAB_REVIEW_INDEX, 0)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _set_review_index(idx: int) -> None:
    app.storage.tab[TAB_REVIEW_INDEX] = idx  # pyright: ignore[reportUnknownMemberType]


def _get_review_scores() -> list[float]:
    return app.storage.tab.get(TAB_REVIEW_SCORES, [])  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _append_review_score(score: float) -> None:
    scores = _get_review_scores()
    scores.append(score)
    app.storage.tab[TAB_REVIEW_SCORES] = scores  # pyright: ignore[reportUnknownMemberType]


def _get_show_back() -> bool:
    return app.storage.tab.get(TAB_REVIEW_SHOW_BACK, False)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _set_show_back(value: bool) -> None:
    app.storage.tab[TAB_REVIEW_SHOW_BACK] = value  # pyright: ignore[reportUnknownMemberType]


def _get_recall_text() -> str:
    return app.storage.tab.get(TAB_REVIEW_RECALL_TEXT, "")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _set_recall_text(value: str) -> None:
    app.storage.tab[TAB_REVIEW_RECALL_TEXT] = value  # pyright: ignore[reportUnknownMemberType]


def _reset_session_state() -> None:
    app.storage.tab[TAB_REVIEW_INDEX] = 0  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_REVIEW_SCORES] = []  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_REVIEW_SHOW_BACK] = False  # pyright: ignore[reportUnknownMemberType]
    app.storage.tab[TAB_REVIEW_RECALL_TEXT] = ""  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------------
# Core review session
# ---------------------------------------------------------------------------


@ui.refreshable  # type: ignore[misc]
async def _review_session() -> None:
    """Fetch due reviews and render the current review state."""
    container = get_container()
    if not container:
        loading_spinner(text="Connecting...")
        return

    try:
        db = container.db  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        reviews = await get_due_review_items(db)  # pyright: ignore[reportUnknownArgumentType]
    except Exception:
        log.exception("review_fetch_failed")
        skeleton_card()
        return

    if not reviews:
        _render_empty_state()
        return

    idx = _get_review_index()

    # All reviews completed this session
    if idx >= len(reviews):
        scores = _get_review_scores()
        _render_session_summary(total=len(reviews), scores=scores)
        _reset_session_state()
        return

    card = reviews[idx]
    # Aria-live announcer for card transitions
    ui.label(f"Card {idx + 1} of {len(reviews)}").classes("sr-only").props('aria-live="polite"')
    _render_progress_label(idx, len(reviews))
    _render_card_stats(difficulty=card.difficulty, stability=card.stability)
    _render_active_card(card, reviews)


def _render_active_card(card: ReviewSchedule, reviews: list[ReviewSchedule]) -> None:
    """Render the current card with recall input or rating buttons."""
    show_back = _get_show_back()
    recall_text = _get_recall_text()

    def _handle_recall(text: str) -> None:
        _set_show_back(True)
        _set_recall_text(text)
        _review_session.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

    async def _handle_rate(rating: int) -> None:
        score = rating_to_score(rating)
        _append_review_score(score)
        _set_review_index(_get_review_index() + 1)
        _set_show_back(False)
        _set_recall_text("")

        try:
            container = get_container()
            if container:
                db = container.db  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
                await complete_review_item(db, card.topic, card.course_id, score)  # pyright: ignore[reportUnknownArgumentType]
        except Exception:
            log.exception("review_complete_failed", topic=card.topic)

        _review_session.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

    previews = compute_interval_previews(card.difficulty, card.stability)
    review_card(
        front=card.topic,
        back=f"Review: {card.topic}",
        on_submit_recall=_handle_recall,
        on_rate=_handle_rate,  # pyright: ignore[reportArgumentType]
        interval_previews=previews,
        show_back=show_back,
        recall_text=recall_text,
    )

    # Keyboard shortcuts
    def _handle_key(e: KeyEventArguments) -> None:
        if not e.action:  # pyright: ignore[reportUnknownMemberType]
            return
        key = e.key  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        if key == "Escape":  # pyright: ignore[reportUnknownMemberType]
            ui.navigate.to("/")
        elif not _get_show_back() and key == " ":  # pyright: ignore[reportUnknownMemberType]
            _handle_recall("")
        elif _get_show_back() and key in ("1", "2", "3", "4"):  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            ui.timer(0, lambda r=int(str(key)): _handle_rate(r), once=True)  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]

    ui.keyboard(on_key=_handle_key)
