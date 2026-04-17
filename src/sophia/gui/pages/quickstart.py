"""Quickstart wizard — 5-step first-launch dialog with scaffold fading."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from nicegui import app, ui

from sophia.gui.services.quickstart_service import (
    get_completed_session_count,
    get_enrolled_courses,
    get_nearest_deadline,
    get_topics_for_courses,
    save_initial_confidence,
)
from sophia.gui.state.storage_map import (
    USER_QUICKSTART_COMPLETED,
    USER_QUICKSTART_SELECTED_COURSES,
    USER_QUICKSTART_SKIPPED,
)

if TYPE_CHECKING:
    from sophia.domain.models import TopicMapping
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# Scaffold fading thresholds
_THRESHOLD_ABBREVIATED = 3
_THRESHOLD_MINIMAL = 5
_THRESHOLD_OPEN = 10


# ---------------------------------------------------------------------------
# Pure helpers — testable without NiceGUI
# ---------------------------------------------------------------------------


def compute_scaffold_level(session_count: int) -> int:
    """Return scaffold level: 3=full, 2=abbreviated, 1=minimal, 0=open."""
    if session_count >= _THRESHOLD_OPEN:
        return 0
    if session_count >= _THRESHOLD_MINIMAL:
        return 1
    if session_count >= _THRESHOLD_ABBREVIATED:
        return 2
    return 3


def suggest_first_action(
    deadlines: list[dict[str, Any]],
    topics: list[str],
) -> tuple[str, str]:
    """Return (message, link_path) suggesting the student's first action."""
    if deadlines:
        nearest = min(deadlines, key=lambda d: d["due_at"])
        days = max(0, (nearest["due_at"] - datetime.now(UTC)).days)
        unit = "day" if days == 1 else "days"
        return (
            f"Your nearest deadline is {nearest['name']} in {days} {unit}. Head to Deadlines.",
            "/chronos",
        )
    if topics:
        return "Try a study session on your weakest topic.", "/study"
    return "Sync your courses first in Settings.", "/settings"


def format_confidence_prompt(scaffold_level: int) -> str:
    """Return scaffold-aware prompt text for confidence rating step."""
    if scaffold_level >= 3:
        return (
            "Rate your confidence on each topic from 1 (no idea) to 5 (could teach it). "
            "This prediction is part of the predict→act→reflect cycle — "
            "you'll compare it with your actual performance later."
        )
    if scaffold_level == 2:
        return (
            "Rate your confidence 1–5 on each topic. "
            "You'll revisit these predictions after studying."
        )
    if scaffold_level == 1:
        return "Rate your confidence 1–5 per topic."
    return "Confidence ratings:"


def format_prediction_guidance(scaffold_level: int) -> str:
    """Return scaffold-aware guidance text for manual topic prediction step."""
    if scaffold_level >= 3:
        return (
            "What topics do you think this course covers? "
            "Generating expectations activates prior knowledge — "
            "even rough guesses improve learning. "
            "After your first sync, you'll see how your predictions compare "
            "to actual course content."
        )
    if scaffold_level == 2:
        return (
            "What topics do you expect to cover? "
            "You'll compare these with actual course topics later."
        )
    if scaffold_level == 1:
        return "Enter expected topics:"
    return ""


def format_skip_text(scaffold_level: int) -> str:
    """Return scaffold-aware text for the skip-prediction option."""
    if scaffold_level >= 2:
        return (
            "Even a rough guess activates prior knowledge and improves learning. "
            "But if you prefer, you can set predictions later from the Study page."
        )
    return "You can set predictions later from the Study page."


# ---------------------------------------------------------------------------
# Wizard dialog
# ---------------------------------------------------------------------------


async def show_quickstart_wizard(container: AppContainer) -> None:
    """Show the 5-step quickstart wizard as a modal dialog."""
    session_count = await get_completed_session_count(container)
    scaffold = compute_scaffold_level(session_count)

    # Refreshable handles — populated by steps 3 and 5, triggered by step 2 advance
    _refreshables: list[Any] = []

    with (
        ui.dialog().props("persistent maximized") as dialog,
        ui.card().classes("w-full max-w-2xl mx-auto"),
    ):
        with ui.stepper().props("vertical").classes("w-full") as stepper:
            _step_welcome(stepper, scaffold)
            await _step_courses(stepper, container, _refreshables)
            await _step_predictions(stepper, container, scaffold, _refreshables)
            _step_feature_tour(stepper, scaffold)
            await _step_first_action(stepper, container, dialog, _refreshables)

        with ui.row().classes("w-full justify-between items-center mt-2"):
            ui.label("You can re-run this wizard anytime from Settings.").classes(
                "text-xs text-gray-400 italic"
            )
            ui.button(
                "Skip",
                icon="skip_next",
                on_click=lambda: _skip_wizard(dialog),
            ).props("flat")

    dialog.open()


def _close_wizard(dialog: ui.dialog) -> None:
    """Mark wizard completed and close."""
    app.storage.user[USER_QUICKSTART_COMPLETED] = True
    app.storage.user[USER_QUICKSTART_SKIPPED] = False
    dialog.close()


def _skip_wizard(dialog: ui.dialog) -> None:
    """Mark wizard skipped (not completed) and close."""
    app.storage.user[USER_QUICKSTART_SKIPPED] = True
    dialog.close()


# ---------------------------------------------------------------------------
# Step 1: Welcome & Philosophy
# ---------------------------------------------------------------------------


def _step_welcome(stepper: ui.stepper, scaffold: int) -> None:
    with ui.step("Welcome to Sophia"):
        ui.label("Welcome to Sophia").classes("text-xl font-bold mb-2")

        if scaffold >= 3:
            ui.markdown(
                "Sophia uses a **constructivist** learning approach: "
                "**Predict → Act → Reflect**. "
                "Before studying, you predict your understanding. "
                "After studying, you compare prediction with reality. "
                "This calibration loop accelerates genuine learning."
            )

        ui.label("What's your current approach to studying? What works and what doesn't?").classes(
            "mt-3 mb-1 font-medium"
        )
        ui.textarea(
            placeholder="This isn't graded — it helps you reflect on your starting point",
        ).classes("w-full").props("rows=3")

        with ui.stepper_navigation():
            ui.button("Next", on_click=stepper.next)


# ---------------------------------------------------------------------------
# Step 2: Course Selection
# ---------------------------------------------------------------------------


async def _step_courses(
    stepper: ui.stepper,
    container: AppContainer,
    refreshables: list[Any],
) -> None:
    courses = await get_enrolled_courses(container)

    with ui.step("Course Selection"):
        selected: dict[int, bool] = {}
        if not courses:
            ui.label("No courses found — authenticate first.").classes("text-amber-600")
            ui.button("Go to Settings", on_click=lambda: ui.navigate.to("/settings")).props(
                "outline"
            )
        else:
            ui.label("Select courses to focus on:").classes("font-medium mb-2")
            for course in courses:
                cb = ui.checkbox(course.fullname, value=True)
                selected[course.id] = True

                def _toggle(cid: int = course.id, checkbox: ui.checkbox = cb) -> None:
                    selected[cid] = checkbox.value

                cb.on_value_change(_toggle)

        async def _advance_and_save() -> None:
            chosen = [cid for cid, on in selected.items() if on]
            app.storage.user[USER_QUICKSTART_SELECTED_COURSES] = chosen
            for refresh_fn in refreshables:
                refresh_fn()
            stepper.next()

        with ui.stepper_navigation():
            ui.button("Next", on_click=_advance_and_save)
            ui.button("Back", on_click=stepper.previous).props("flat")


# ---------------------------------------------------------------------------
# Step 3: Topic Preview & First Prediction
# ---------------------------------------------------------------------------


async def _step_predictions(
    stepper: ui.stepper,
    container: AppContainer,
    scaffold: int,
    refreshables: list[Any],
) -> None:
    with ui.step("First Prediction"):

        @ui.refreshable
        async def _content() -> None:
            selected_ids: list[int] = app.storage.user.get(USER_QUICKSTART_SELECTED_COURSES, [])
            topics: list[TopicMapping] = []
            if selected_ids:
                topics = await get_topics_for_courses(container, selected_ids)

            displayed_topics = topics[:5]

            if not displayed_topics:
                ui.label("Topics will appear after your first study sync.").classes(
                    "text-gray-500 italic"
                )
            else:
                prompt = format_confidence_prompt(scaffold)
                ui.label(prompt).classes("mb-3")

                ratings: dict[str, int] = {}
                for tm in displayed_topics:
                    with ui.row().classes("items-center gap-2 mb-2"):
                        ui.label(tm.topic).classes("w-48 truncate")
                        group = ui.button_group()
                        with group:
                            for level in range(1, 6):

                                def _rate(
                                    topic: str = tm.topic,
                                    val: int = level,
                                ) -> None:
                                    ratings[topic] = val

                                ui.button(str(level), on_click=_rate).props("flat dense")

                async def _save_ratings() -> None:
                    if ratings and displayed_topics:
                        course_id = displayed_topics[0].course_id
                        await save_initial_confidence(
                            container, course_id=course_id, ratings=ratings
                        )
                        ui.notify("Predictions saved!", type="positive")

                ui.button("Save Predictions", on_click=_save_ratings).props("outline").classes(
                    "mt-2"
                )

                ui.label("You've made your first predictions! Let's see how they hold up.").classes(
                    "text-sm text-gray-500 mt-2 italic"
                )

        await _content()
        refreshables.append(_content.refresh)

        with ui.stepper_navigation():
            ui.button("Next", on_click=stepper.next)
            ui.button("Back", on_click=stepper.previous).props("flat")


# ---------------------------------------------------------------------------
# Step 4: Feature Tour
# ---------------------------------------------------------------------------


def _step_feature_tour(stepper: ui.stepper, scaffold: int) -> None:
    with ui.step("Feature Tour"):
        ui.label("Your Learning Hub").classes("text-lg font-bold mb-2")

        pages = [
            ("Dashboard", "dashboard", "Overview of your academic landscape"),
            ("Study", "school", "Guided study sessions with the predict→act→reflect cycle"),
            ("Review", "rate_review", "Spaced-repetition review of mastered topics"),
            ("Deadlines", "schedule", "Deadline coaching and time estimation calibration"),
        ]
        for label, icon, desc in pages:
            with ui.row().classes("items-center gap-3 mb-2"):
                ui.icon(icon).classes("text-xl text-blue-600")
                with ui.column().classes("gap-0"):
                    ui.label(label).classes("font-semibold")
                    ui.label(desc).classes("text-sm text-gray-600")

        if scaffold >= 2:
            ui.separator().classes("my-3")
            ui.markdown(
                "**The pedagogical cycle:** Predict → Study → Reflect\n\n"
                "**Progressive disclosure modes:**\n"
                "- **Focus** — essential information only\n"
                "- **Standard** — balanced view\n"
                "- **Full** — all details visible"
            )

        with ui.stepper_navigation():
            ui.button("Next", on_click=stepper.next)
            ui.button("Back", on_click=stepper.previous).props("flat")


# ---------------------------------------------------------------------------
# Step 5: First Action
# ---------------------------------------------------------------------------


async def _step_first_action(
    stepper: ui.stepper,
    container: AppContainer,
    dialog: ui.dialog,
    refreshables: list[Any],
) -> None:
    with ui.step("Get Started"):

        @ui.refreshable
        async def _content() -> None:
            deadline = await get_nearest_deadline(container)
            selected_ids: list[int] = app.storage.user.get(USER_QUICKSTART_SELECTED_COURSES, [])
            topics: list[TopicMapping] = []
            if selected_ids:
                topics = await get_topics_for_courses(container, selected_ids)

            deadlines_data: list[dict[str, Any]] = []
            if deadline:
                deadlines_data = [{"name": deadline.name, "due_at": deadline.due_at}]

            topic_names = [t.topic for t in topics[:5]]
            msg, path = suggest_first_action(deadlines_data, topic_names)

            ui.label("Your First Step").classes("text-lg font-bold mb-2")
            ui.label(msg).classes("text-base mb-4")

            def _go() -> None:
                _close_wizard(dialog)
                ui.navigate.to(path)

            ui.button("Get Started", icon="rocket_launch", on_click=_go).props("color=primary")

        await _content()
        refreshables.append(_content.refresh)

        with ui.stepper_navigation():
            ui.button("Back", on_click=stepper.previous).props("flat")
