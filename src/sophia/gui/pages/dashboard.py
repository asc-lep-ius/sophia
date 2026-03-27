"""Dashboard page — progressive-disclosure overview of the student's academic landscape."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from nicegui import app, ui

from sophia.domain.models import DeadlineType, PlanItemType
from sophia.gui.components.loading import loading_spinner, skeleton_card
from sophia.gui.middleware.health import get_container
from sophia.gui.state.storage_map import BROWSER_DENSITY_MODE
from sophia.services.athena_chronos import build_plan_items
from sophia.services.athena_review import get_due_reviews
from sophia.services.chronos import get_deadlines

if TYPE_CHECKING:
    from sophia.domain.models import Deadline, PlanItem, ReviewSchedule

log = structlog.get_logger()

# Density mode identifiers
DENSITY_FOCUS = "focus"
DENSITY_STANDARD = "standard"
DENSITY_FULL = "full"

# Theming colors — always paired with icon + text labels for accessibility
COLOR_RETAINED = "#15803d"
COLOR_REVIEW_SOON = "#b45309"
COLOR_OVERDUE = "#b91c1c"
COLOR_ACTIVE = "#1d4ed8"
COLOR_NOT_STUDIED = "#6b7280"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def dashboard_content() -> None:
    """Main dashboard entry point — called by app_shell + error_boundary."""
    _render_header()
    await _dashboard_cards()


# ---------------------------------------------------------------------------
# Layout and data orchestration
# ---------------------------------------------------------------------------


def _render_header() -> None:
    with ui.row().classes("w-full items-center justify-between mb-4"):
        ui.label("Dashboard").classes("text-2xl font-bold")
        _render_density_toggle()


@ui.refreshable  # type: ignore[misc]
def _render_density_toggle() -> None:
    current: str = app.storage.browser.get(BROWSER_DENSITY_MODE, DENSITY_STANDARD)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]

    def _set_mode(mode: str) -> None:
        app.storage.browser[BROWSER_DENSITY_MODE] = mode  # pyright: ignore[reportUnknownMemberType]
        _render_density_toggle.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]
        _dashboard_cards.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

    with ui.button_group():
        for mode, icon, label in [
            (DENSITY_FOCUS, "center_focus_strong", "Focus"),
            (DENSITY_STANDARD, "view_module", "Standard"),
            (DENSITY_FULL, "view_comfy", "Full"),
        ]:
            btn = ui.button(label, icon=icon, on_click=lambda _e, m=mode: _set_mode(m))
            btn.props(f'aria-label="Dashboard density: {label}"')
            if mode == current:
                btn.props("color=primary")
            else:
                btn.props("flat text-color=dark")


@ui.refreshable  # type: ignore[misc]
async def _dashboard_cards() -> None:
    """Fetch data and render density-appropriate cards."""
    container = get_container()
    if not container:
        loading_spinner(text="Connecting...")
        return

    density: str = app.storage.browser.get(BROWSER_DENSITY_MODE, DENSITY_STANDARD)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]

    try:
        db = container.db  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        reviews = await get_due_reviews(db)  # pyright: ignore[reportUnknownArgumentType]
        deadlines = await get_deadlines(db)  # pyright: ignore[reportUnknownArgumentType]
        plan_items = await build_plan_items(db)  # pyright: ignore[reportUnknownArgumentType]
    except Exception:
        log.exception("dashboard_data_fetch_failed")
        skeleton_card()
        return

    with ui.column().classes("w-full transition-opacity duration-200"):
        if density == DENSITY_FOCUS:
            _render_focus_mode(reviews, deadlines, plan_items)
        elif density == DENSITY_FULL:
            _render_full_mode(reviews, deadlines, plan_items)
        else:
            _render_standard_mode(reviews, deadlines, plan_items)


# ---------------------------------------------------------------------------
# Density mode renderers
# ---------------------------------------------------------------------------


def _render_focus_mode(
    reviews: list[ReviewSchedule],
    deadlines: list[Deadline],
    plan_items: list[PlanItem],
) -> None:
    """Minimal view: due count + Socratic prompt."""
    _render_due_reviews_card(reviews)
    _render_socratic_prompt(reviews, deadlines, plan_items)


def _render_standard_mode(
    reviews: list[ReviewSchedule],
    deadlines: list[Deadline],
    plan_items: list[PlanItem],
) -> None:
    """Default view: reviews + deadlines + plan items + prompt."""
    with ui.row().classes("w-full gap-4 flex-wrap"):
        with ui.column().classes("flex-1 min-w-[300px]"):
            _render_due_reviews_card(reviews)
            _render_deadlines_card(deadlines)
        with ui.column().classes("flex-1 min-w-[300px]"):
            _render_plan_items_card(plan_items)
    _render_socratic_prompt(reviews, deadlines, plan_items)


def _render_full_mode(
    reviews: list[ReviewSchedule],
    deadlines: list[Deadline],
    plan_items: list[PlanItem],
) -> None:
    """Full view: everything from standard + chart placeholders."""
    _render_standard_mode(reviews, deadlines, plan_items)
    with ui.row().classes("w-full gap-4 flex-wrap mt-4"):
        _render_chart_placeholder("Calibration chart", "tune")
        _render_chart_placeholder("Activity chart", "bar_chart")


# ---------------------------------------------------------------------------
# Card renderers
# ---------------------------------------------------------------------------


def _render_due_reviews_card(reviews: list[ReviewSchedule]) -> None:
    """Card showing count of due reviews with link to /review."""
    due = [r for r in reviews if r.is_due]
    count = len(due)
    color = COLOR_OVERDUE if count > 0 else COLOR_RETAINED
    icon = "rate_review" if count > 0 else "check_circle"

    with ui.card().classes("w-full p-4"):
        with ui.row().classes("items-center gap-3"):
            ui.icon(icon).style(f"color: {color}").classes("text-3xl")
            with ui.column().classes("gap-0"):
                ui.label(f"{count} review{'s' if count != 1 else ''} due").classes(
                    "text-lg font-semibold",
                )
                if due:
                    topics = ", ".join(r.topic for r in due[:3])
                    ui.label(topics).classes("text-sm text-gray-500")
        if due:
            ui.button("Start Review", on_click=lambda: ui.navigate.to("/review")).classes("mt-2")
        else:
            ui.label("All caught up!").classes("text-sm mt-2").style(f"color: {COLOR_RETAINED}")


def _render_deadlines_card(deadlines: list[Deadline]) -> None:
    """Top 3 upcoming deadlines."""
    with ui.card().classes("w-full p-4"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("event").classes("text-xl").style(f"color: {COLOR_ACTIVE}")
            ui.label("Upcoming Deadlines").classes("font-semibold")

        if not deadlines:
            with ui.column().classes("items-center py-4"):
                ui.icon("event_note", color="gray").classes("text-3xl")
                ui.label("No deadlines yet").classes("text-sm font-semibold text-gray-600 mt-2")
                ui.label(
                    "Sync your TUWEL deadlines to start"
                    " the predict \u2192 act \u2192 reflect cycle."
                ).classes("text-xs text-gray-500 text-center mt-1")
                ui.button(
                    "Sync Deadlines",
                    icon="sync",
                    on_click=lambda: ui.navigate.to("/chronos"),
                ).props("flat dense").classes("mt-2")
            return

        for d in deadlines[:3]:
            days_until = (d.due_at - datetime.now(UTC)).days
            color = _deadline_urgency_color(days_until)
            icon = _deadline_type_icon(d.deadline_type)

            with ui.row().classes("items-center gap-2 py-1"):
                ui.icon(icon).style(f"color: {color}").classes("text-lg")
                with ui.column().classes("gap-0"):
                    ui.label(d.name).classes("text-sm font-medium")
                    ui.label(f"{d.course_name} · {_format_days(days_until)}").classes(
                        "text-xs text-gray-500",
                    )


def _render_plan_items_card(plan_items: list[PlanItem]) -> None:
    """Top plan items — ranked by score."""
    with ui.card().classes("w-full p-4"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon("playlist_play").classes("text-xl").style(f"color: {COLOR_ACTIVE}")
            ui.label("Academic Landscape").classes("font-semibold")

        if not plan_items:
            with ui.column().classes("items-center py-4"):
                ui.icon("playlist_add_check", color="gray").classes("text-3xl")
                ui.label("No plan items").classes("text-sm font-semibold text-gray-600 mt-2")
                ui.label(
                    "Plan items appear after syncing deadlines and rating confidence per topic."
                ).classes("text-xs text-gray-500 text-center mt-1")
            return

        for item in plan_items[:5]:
            icon = _plan_item_icon(item.item_type)
            color = _plan_item_color(item.item_type)

            with ui.row().classes("items-center gap-2 py-1"):
                ui.icon(icon).style(f"color: {color}").classes("text-lg")
                with ui.column().classes("gap-0"):
                    ui.label(item.title).classes("text-sm font-medium")
                    parts = [item.course_name]
                    if item.due_at:
                        parts.append(item.due_at[:10])
                    if item.detail:
                        parts.append(item.detail)
                    ui.label(" · ".join(parts)).classes("text-xs text-gray-500")


def _render_socratic_prompt(
    reviews: list[ReviewSchedule],
    deadlines: list[Deadline],
    plan_items: list[PlanItem],
) -> None:
    """Render a Socratic question card if data supports one."""
    prompt = _get_socratic_prompt(reviews, deadlines, plan_items)
    if not prompt:
        return

    with (
        ui.card()
        .classes("w-full p-4 mt-4 border-l-4")
        .style(
            f"border-left-color: {COLOR_ACTIVE}",
        ),
        ui.row().classes("items-start gap-3"),
    ):
        ui.icon("psychology").classes("text-2xl").style(f"color: {COLOR_ACTIVE}")
        ui.label(prompt).classes("text-sm italic")


def _render_chart_placeholder(title: str, icon_name: str) -> None:
    """Placeholder card for charts coming in Phase 6."""
    with ui.card().classes("flex-1 min-w-[300px] p-4"):
        with ui.row().classes("items-center gap-2 mb-2"):
            ui.icon(icon_name).classes("text-xl").style(f"color: {COLOR_NOT_STUDIED}")
            ui.label(title).classes("font-semibold text-gray-400")
        ui.label(f"{title} — coming in Phase 6").classes(
            "text-sm text-gray-400 italic py-8 text-center",
        )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _get_socratic_prompt(
    due_reviews: list[ReviewSchedule],
    deadlines: list[Deadline],
    plan_items: list[PlanItem],
) -> str | None:
    """Generate a data-driven Socratic question. Never prescriptive."""
    # Exam approaching — highest priority
    exams = [d for d in deadlines if d.deadline_type == DeadlineType.EXAM]
    if exams:
        nearest = exams[0]
        days = (nearest.due_at - datetime.now(UTC)).days
        return (
            f"Your next exam ({nearest.name}) is in "
            f"{days} day{'s' if days != 1 else ''}. "
            "Which topic would you least want to be tested on right now?"
        )

    # Multiple confidence gaps
    gaps = [i for i in plan_items if i.item_type == PlanItemType.CONFIDENCE_GAP]
    if len(gaps) >= 2:
        return (
            f"There are {len(gaps)} topics flagged as confidence gaps. "
            "What do those topics have in common?"
        )

    # Due reviews
    due = [r for r in due_reviews if r.is_due]
    if due:
        if len(due) >= 2:
            first, last = due[0].topic, due[-1].topic
            if first != last:
                return (
                    f'"{first}" has been waiting longest for review, '
                    f'while "{last}" was added most recently. '
                    "Which feels more uncertain right now?"
                )
        return (
            f"You have {len(due)} topic{'s' if len(due) != 1 else ''} "
            "due for review. Which one do you remember least about?"
        )

    # Anything in the plan
    if plan_items:
        n = len(plan_items)
        return (
            f"Your academic landscape has {n} item{'s' if n != 1 else ''}. "
            "Is there anything you've been avoiding?"
        )

    return None


def _deadline_urgency_color(days_until: int) -> str:
    if days_until <= 1:
        return COLOR_OVERDUE
    if days_until <= 3:
        return COLOR_REVIEW_SOON
    return COLOR_ACTIVE


def _deadline_type_icon(deadline_type: DeadlineType) -> str:
    icons: dict[DeadlineType, str] = {
        DeadlineType.EXAM: "school",
        DeadlineType.QUIZ: "quiz",
        DeadlineType.ASSIGNMENT: "assignment",
        DeadlineType.CHECKMARK: "check_box",
        DeadlineType.EXAM_REGISTRATION: "how_to_reg",
    }
    return icons.get(deadline_type, "event")


def _format_days(days: int) -> str:
    if days < 0:
        return "overdue"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


def _plan_item_icon(item_type: PlanItemType) -> str:
    icons: dict[PlanItemType, str] = {
        PlanItemType.DEADLINE: "event",
        PlanItemType.REVIEW: "rate_review",
        PlanItemType.CONFIDENCE_GAP: "trending_down",
        PlanItemType.MISSED_TOPIC: "visibility_off",
    }
    return icons.get(item_type, "circle")


def _plan_item_color(item_type: PlanItemType) -> str:
    colors: dict[PlanItemType, str] = {
        PlanItemType.DEADLINE: COLOR_ACTIVE,
        PlanItemType.REVIEW: COLOR_REVIEW_SOON,
        PlanItemType.CONFIDENCE_GAP: COLOR_OVERDUE,
        PlanItemType.MISSED_TOPIC: COLOR_NOT_STUDIED,
    }
    return colors.get(item_type, COLOR_NOT_STUDIED)
