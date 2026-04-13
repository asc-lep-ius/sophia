"""Topics management page — view extracted topics, trigger extraction, confidence overview."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

import structlog
from nicegui import app, ui

from sophia.gui.components.confidence_rating import confidence_rating
from sophia.gui.middleware.health import get_container
from sophia.gui.services.topic_service import (
    export_anki_deck,
    extract_topics,
    get_course_topics,
    get_topic_confidence,
    save_confidence_prediction,
)
from sophia.gui.state.storage_map import USER_CURRENT_COURSE

if TYPE_CHECKING:
    from sophia.domain.models import ConfidenceRating, TopicMapping
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# --- Constants ---------------------------------------------------------------

SOURCE_BADGE_COLORS: Final[dict[str, str]] = {
    "lecture": "blue",
    "quiz": "purple",
    "manual": "grey",
}

_CONFIDENCE_THRESHOLDS: Final[list[tuple[float, str]]] = [
    (0.2, "No idea"),
    (0.4, "Guessing"),
    (0.6, "Partial"),
    (0.8, "Mostly right"),
    (1.01, "Certain"),
]

CALIBRATION_LABELS: Final[dict[str, str]] = {
    "pending": "Pending",
    "well_calibrated": "Well calibrated",
    "slightly_over": "Slightly overconfident",
    "slightly_under": "Slightly underconfident",
    "blind_spot": "Blind spot",
    "underconfident": "Underconfident",
}

_CALIBRATION_COLORS: Final[dict[str, str]] = {
    "pending": "grey",
    "well_calibrated": "positive",
    "slightly_over": "warning",
    "slightly_under": "info",
    "blind_spot": "negative",
    "underconfident": "accent",
}

_BLIND_SPOT_THRESHOLD: Final = 0.2

ANKI_NUDGE_TEXT: Final = (
    "Auto-generated cards are a starting point. Review and personalize them for deeper learning."
)


# --- Pure helpers (testable) -------------------------------------------------


def format_confidence_level(score: float | None) -> str:
    """Map a 0.0-1.0 confidence score to a human-readable label."""
    if score is None:
        return "Not rated"
    for threshold, label in _CONFIDENCE_THRESHOLDS:
        if score < threshold:
            return label
    return "Certain"


def classify_calibration(error: float | None) -> str:
    """Classify a calibration error into a category string."""
    if error is None:
        return "pending"
    abs_error = abs(error)
    if abs_error <= 0.1:
        return "well_calibrated"
    if error > _BLIND_SPOT_THRESHOLD:
        return "blind_spot"
    if error > 0:
        return "slightly_over"
    if abs_error > _BLIND_SPOT_THRESHOLD:
        return "underconfident"
    return "slightly_under"


# --- Page entry point -------------------------------------------------------


async def topics_content() -> None:
    """Public entry point for the topics management page."""
    container = get_container()
    if container is None:
        ui.label("Application not initialized.").classes("text-red-700")
        return

    course_id: int | None = app.storage.user.get(USER_CURRENT_COURSE)
    if course_id is None:
        with ui.column().classes("w-full items-center py-12"):
            ui.icon("topic", color="gray").classes("text-6xl")
            ui.label("Select a course from the Dashboard to begin.").classes("text-gray-500 mt-4")
            ui.link("Go to Dashboard", "/").classes("mt-2")
        return

    _render_header(container, course_id)
    await _topic_list(container, course_id)


# --- Header ------------------------------------------------------------------


def _render_header(container: AppContainer, course_id: int) -> None:
    with ui.row().classes("w-full items-center justify-between mb-4"):
        ui.label("Topics").classes("text-2xl font-bold")
        with ui.row().classes("gap-2"):
            _render_export_button(container, course_id)
            ui.button(
                "Extract Topics",
                icon="auto_awesome",
                on_click=lambda: _handle_extract(container, course_id),
            ).props("outline")


async def _handle_extract(container: AppContainer, course_id: int) -> None:
    """Handle topic extraction button click."""
    ui.notify("Extracting topics…", type="info")
    topics = await extract_topics(container, module_id=course_id)
    if topics:
        ui.notify(f"Extracted {len(topics)} topics", type="positive")
        _topic_list.refresh()  # type: ignore[attr-defined]
    else:
        ui.notify("No topics found — ensure lectures are indexed first.", type="warning")


# --- Anki export -------------------------------------------------------------


def _render_export_button(container: AppContainer, course_id: int) -> None:
    """Export Anki Deck button with pedagogical nudge dialog."""
    export_btn = ui.button("Export Anki Deck", icon="style").props("outline")

    async def _handle_anki_export() -> None:
        with ui.dialog() as dialog, ui.card().classes("p-4 min-w-[300px]"):
            ui.label("Export Anki Deck").classes("text-lg font-bold mb-2")
            ui.label(ANKI_NUDGE_TEXT).classes("text-sm text-gray-500 italic mb-4")

            with ui.row().classes("w-full justify-end gap-2 mt-3"):
                ui.button("Cancel", on_click=dialog.close).props("flat")
                ui.button(
                    "Export",
                    on_click=lambda: _do_export(container, course_id, dialog),
                ).props("color=primary")

        dialog.open()

    export_btn.on_click(_handle_anki_export)


async def _do_export(
    container: AppContainer,
    course_id: int,
    dialog: object,
) -> None:
    """Run the actual Anki deck export and trigger browser download."""
    dialog.close()  # type: ignore[union-attr]
    ui.notify("Generating Anki deck…", type="info")
    result = await export_anki_deck(container, course_id=course_id)
    if result is None:
        ui.notify("No flashcards to export — study some topics first.", type="warning")
        return
    ui.download(result, f"sophia_course_{course_id}.apkg")
    ui.notify("Anki deck downloaded!", type="positive")


# --- Topic list (refreshable) -----------------------------------------------


@ui.refreshable
async def _topic_list(container: AppContainer, course_id: int) -> None:
    """Render the list of topics with confidence and calibration info."""
    topics = await get_course_topics(container, course_id=course_id)

    if not topics:
        ui.label("No topics extracted yet — click 'Extract Topics' to get started.").classes(
            "text-gray-400 italic mt-8 text-center w-full"
        )
        return

    for topic_mapping in topics:
        await _render_topic_row(container, course_id, topic_mapping)


async def _render_topic_row(
    container: AppContainer,
    course_id: int,
    topic_mapping: TopicMapping,
) -> None:
    """Render a single topic row with badges and confidence info."""
    rating = await get_topic_confidence(container, course_id=course_id, topic=topic_mapping.topic)

    with ui.card().classes("w-full mb-2"), ui.row().classes("w-full items-center justify-between"):
        # Topic name + source badge
        with ui.row().classes("items-center gap-2"):
            ui.label(topic_mapping.topic).classes("font-medium")
            source_color = SOURCE_BADGE_COLORS.get(topic_mapping.source.value, "grey")
            ui.badge(topic_mapping.source.value.upper(), color=source_color)
            if topic_mapping.frequency > 1:
                ui.badge(f"×{topic_mapping.frequency}", color="grey").props("outline")

        # Confidence + calibration info
        with ui.row().classes("items-center gap-2"):
            _render_confidence_badge(rating)
            _render_calibration_badge(rating)
            ui.button(
                icon="psychology",
                on_click=lambda _, t=topic_mapping.topic: _open_prediction_dialog(
                    container, course_id, t
                ),
            ).props("flat round size=sm").tooltip("Rate confidence")


def _render_confidence_badge(rating: ConfidenceRating | None) -> None:
    """Render a confidence level badge."""
    if rating is None:
        ui.badge("Not rated", color="grey").props("outline")
        return
    label = format_confidence_level(rating.predicted)
    ui.badge(label, color="primary")


def _render_calibration_badge(rating: ConfidenceRating | None) -> None:
    """Render a calibration classification badge."""
    if rating is None:
        return
    classification = classify_calibration(rating.calibration_error)
    label = CALIBRATION_LABELS[classification]
    color = _CALIBRATION_COLORS[classification]
    if classification == "blind_spot":
        ui.badge(f"⚠ {label}", color=color)
    elif classification != "pending":
        ui.badge(label, color=color).props("outline")


# --- Forced prediction dialog -----------------------------------------------


async def _open_prediction_dialog(
    container: AppContainer,
    course_id: int,
    topic: str,
) -> None:
    """Open a dialog for rating confidence on a topic before studying."""
    with ui.dialog() as dialog, ui.card().classes("min-w-[300px]"):
        ui.label("How confident are you about:").classes("text-sm text-gray-600")
        ui.label(topic).classes("text-lg font-bold mb-4")

        async def _on_rate(value: int) -> None:
            result = await save_confidence_prediction(
                container, topic=topic, course_id=course_id, rating=value
            )
            dialog.close()
            if result:
                ui.notify(
                    f"Rated '{topic}' as {format_confidence_level(result.predicted)}",
                    type="positive",
                )
                _topic_list.refresh()  # type: ignore[attr-defined]
            else:
                ui.notify("Failed to save rating", type="negative")

        confidence_rating(on_rate=_on_rate)  # type: ignore[arg-type]
        ui.button("Cancel", on_click=dialog.close).props("flat")

    dialog.open()
