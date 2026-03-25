"""Chronos deadlines page — scaffold-aware effort estimation & time tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog
from nicegui import app, ui

from sophia.gui.services.chronos_service import (
    estimate_effort,
    format_deadline_feedback,
    get_deadline_calibration,
    get_deadline_priority,
    get_deadline_scaffold,
    get_deadline_tracked_time,
    get_upcoming_deadlines,
    reflect_on_deadline,
    start_deadline_timer,
    stop_deadline_timer,
)
from sophia.gui.state.storage_map import (
    GENERAL_APP_CONTAINER,
    TAB_CHRONOS_ACTIVE_TIMER,
    TAB_CHRONOS_COURSE_FILTER,
    TAB_CHRONOS_ESTIMATE_DRAFT,
    USER_CURRENT_COURSE,
)

if TYPE_CHECKING:
    from sophia.domain.models import Deadline, EstimationScaffold
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# --- Constants ---------------------------------------------------------------

_DEADLINE_TYPE_COLORS: Final[dict[str, str]] = {
    "assignment": "green",
    "quiz": "blue",
    "checkmark": "teal",
    "exam": "red",
    "exam_registration": "orange",
}

_HORIZON_DAYS: Final = 30
_BREAKDOWN_CATEGORIES: Final = ["Reading", "Exercises", "Review"]


# --- Pure helpers (testable) -------------------------------------------------


def format_due_date(due_at: datetime, *, now: datetime | None = None) -> str:
    """Format relative due date. E.g., 'in 3 days', 'overdue by 2 days', 'today'."""
    if now is None:
        now = datetime.now(UTC)
    delta = due_at - now
    days = int(delta.total_seconds() // 86400)
    if days > 1:
        return f"in {days} days"
    if days == 1:
        return "in 1 day"
    if days == 0:
        return "today"
    abs_days = abs(days)
    if abs_days == 1:
        return "overdue by 1 day"
    return f"overdue by {abs_days} days"


def format_hours(hours: float) -> str:
    """Format hours as human-readable. E.g., '1.5h', '30min', '0min'."""
    if hours < 1.0:
        minutes = round(hours * 60)
        return f"{minutes}min"
    return f"{hours:.1f}h"


# --- Storage helpers ---------------------------------------------------------


def _get_course_filter() -> int | None:
    val = app.storage.tab.get(TAB_CHRONOS_COURSE_FILTER, None)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    return int(val) if val else None  # pyright: ignore[reportUnknownArgumentType]


def _set_course_filter(course_id: int | None) -> None:
    app.storage.tab[TAB_CHRONOS_COURSE_FILTER] = course_id  # pyright: ignore[reportUnknownMemberType]


def _get_active_timer() -> str:
    return app.storage.tab.get(TAB_CHRONOS_ACTIVE_TIMER, "")  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _set_active_timer(deadline_id: str) -> None:
    app.storage.tab[TAB_CHRONOS_ACTIVE_TIMER] = deadline_id  # pyright: ignore[reportUnknownMemberType]


def _get_estimate_draft() -> dict[str, object]:
    return app.storage.tab.get(TAB_CHRONOS_ESTIMATE_DRAFT, {})  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _set_estimate_draft(draft: dict[str, object]) -> None:
    app.storage.tab[TAB_CHRONOS_ESTIMATE_DRAFT] = draft  # pyright: ignore[reportUnknownMemberType]


def _get_current_course() -> int:  # pyright: ignore[reportUnusedFunction]
    return app.storage.user.get(USER_CURRENT_COURSE, 0)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


# --- Entry point -------------------------------------------------------------


def chronos_content() -> None:
    """Main Chronos deadlines page — called by app_shell + error_boundary."""
    container = app.storage.general.get(GENERAL_APP_CONTAINER)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    if container is None:
        ui.label("Application not initialized.").classes("text-red-500")
        return
    _render_header(container)  # pyright: ignore[reportUnknownArgumentType]
    _deadline_list(container)  # pyright: ignore[reportUnknownArgumentType, reportUnusedCoroutine]
    _render_calibration_chart(container)  # pyright: ignore[reportUnknownArgumentType, reportUnusedCoroutine]


# --- Header ------------------------------------------------------------------


def _render_header(container: AppContainer) -> None:
    with ui.row().classes("w-full items-center justify-between mb-4"):
        ui.label("Deadlines").classes("text-2xl font-bold")
        with ui.row().classes("items-center gap-2"):
            ui.select(
                {0: "All Courses"},
                value=_get_course_filter() or 0,
                on_change=lambda e: _on_course_filter_change(e.value),
            ).classes("min-w-[140px]").props("dense outlined")

            async def _sync() -> None:
                ui.notify("Syncing deadlines…", type="info")
                _deadline_list.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

            ui.button("Sync", icon="sync", on_click=_sync).props("flat dense")


def _on_course_filter_change(value: object) -> None:
    _set_course_filter(int(value) if value else None)  # pyright: ignore[reportUnknownArgumentType, reportArgumentType]
    _deadline_list.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]


# --- Deadline list -----------------------------------------------------------


@ui.refreshable  # type: ignore[misc]
async def _deadline_list(container: AppContainer) -> None:
    """Fetch and render sorted deadline cards."""
    course_filter = _get_course_filter()
    deadlines: list[Deadline] = await get_upcoming_deadlines(
        container,
        course_id=course_filter,
        horizon_days=_HORIZON_DAYS,
    )  # pyright: ignore[reportUnknownArgumentType]

    if not deadlines:
        with ui.column().classes("w-full items-center py-12"):
            ui.icon("event_available", color="gray").classes("text-6xl")
            ui.label("No upcoming deadlines.").classes("text-gray-500 mt-4")
        return

    # Sort by due date
    sorted_deadlines = sorted(deadlines, key=lambda d: d.due_at)  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]

    for deadline in sorted_deadlines:
        await _render_deadline_card(container, deadline)  # pyright: ignore[reportUnknownArgumentType]


# --- Deadline card -----------------------------------------------------------


async def _render_deadline_card(container: AppContainer, deadline: Deadline) -> None:
    """Render a single deadline card with info, priority, and actions."""
    priority = await get_deadline_priority(deadline, container)  # pyright: ignore[reportUnknownArgumentType]
    tracked = await get_deadline_tracked_time(container, deadline.id)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
    active_timer = _get_active_timer()

    with ui.card().classes("w-full p-4 mb-3"):
        # Top row: type badge + name + course
        with ui.row().classes("w-full items-center justify-between"):
            with ui.row().classes("items-center gap-2"):
                color = _DEADLINE_TYPE_COLORS.get(deadline.deadline_type.value, "gray")  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                ui.badge(
                    deadline.deadline_type.value.upper(),  # pyright: ignore[reportUnknownMemberType]
                    color=color,
                ).classes("text-xs")
                ui.label(deadline.name).classes("font-bold")  # pyright: ignore[reportUnknownMemberType]

            ui.label(deadline.course_name).classes("text-sm text-gray-500")  # pyright: ignore[reportUnknownMemberType]

        # Due date + progress
        with ui.row().classes("w-full items-center justify-between mt-2"):
            due_text = format_due_date(deadline.due_at)  # pyright: ignore[reportUnknownArgumentType]
            overdue = "overdue" in due_text
            due_cls = "text-sm text-red-500 font-bold" if overdue else "text-sm text-gray-600"
            ui.label(due_text).classes(due_cls)

            # Hours progress bar
            draft = _get_estimate_draft()
            is_match = draft.get("deadline_id") == deadline.id  # pyright: ignore[reportUnknownMemberType]
            estimated = float(draft.get("predicted_hours", 0) if is_match else 0)  # pyright: ignore[reportUnknownMemberType, reportArgumentType]
            if estimated > 0:
                progress = min(tracked / estimated, 1.0) if estimated else 0.0
                with ui.row().classes("items-center gap-1 text-xs"):
                    ui.label(f"{format_hours(tracked)} / {format_hours(estimated)}")
                    ui.linear_progress(value=progress).classes("w-24").props("rounded")

        # Priority score (transparent breakdown)
        if priority:
            _render_priority(priority)

        # Action buttons
        with ui.row().classes("mt-2 gap-2"):

            async def _show_estimate(dl: Deadline = deadline) -> None:  # pyright: ignore[reportUnknownParameterType]
                await _render_estimation_form(container, dl)  # pyright: ignore[reportUnknownArgumentType]

            ui.button("Estimate", icon="calculate", on_click=_show_estimate).props("flat dense")

            is_running = active_timer == deadline.id  # pyright: ignore[reportUnknownMemberType]
            if is_running:

                async def _stop(dl: Deadline = deadline) -> None:  # pyright: ignore[reportUnknownParameterType]
                    elapsed = await stop_deadline_timer(container, dl.id)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
                    _set_active_timer("")
                    ui.notify(f"Stopped — {format_hours(elapsed)} tracked", type="positive")
                    _deadline_list.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

                ui.button("Stop ⏹", icon="stop", on_click=_stop).props("flat dense color=negative")
            else:

                async def _start(dl: Deadline = deadline) -> None:  # pyright: ignore[reportUnknownParameterType]
                    current = _get_active_timer()
                    if current and current != dl.id:  # pyright: ignore[reportUnknownMemberType]
                        msg = "Another timer is already running. Stop it first."
                        ui.notify(msg, type="warning")
                        return
                    await start_deadline_timer(container, dl.id)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
                    _set_active_timer(dl.id)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                    ui.notify("Timer started", type="positive")
                    _deadline_list.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

                ui.button("Start Timer", icon="play_arrow", on_click=_start).props("flat dense")

            # Reflection for overdue deadlines
            now_utc = datetime.now(UTC)
            if deadline.due_at < now_utc:  # pyright: ignore[reportUnknownMemberType]

                async def _show_reflect(dl: Deadline = deadline) -> None:  # pyright: ignore[reportUnknownParameterType]
                    await _render_reflection_form(container, dl)  # pyright: ignore[reportUnknownArgumentType]

                ui.button("Reflect", icon="psychology", on_click=_show_reflect).props("flat dense")

        # Timer display if active
        if active_timer == deadline.id:  # pyright: ignore[reportUnknownMemberType]
            _render_timer_display()


# --- Priority display --------------------------------------------------------


def _render_priority(score: dict[str, float]) -> None:
    """Show priority score with transparent component breakdown."""
    if not score:
        return
    with ui.row().classes("items-center gap-2 text-xs mt-1"):
        total = score.get("score", 0)
        ui.label(f"Priority: {total:.2f}").classes("font-bold")
        ui.badge(f"U:{score.get('urgency', 0):.1f}", color="red").classes("text-xs")
        ui.badge(f"I:{score.get('importance', 0):.1f}", color="blue").classes("text-xs")
        ui.badge(f"G:{score.get('effort_gap', 0):.1f}", color="orange").classes("text-xs")


# --- Estimation form ---------------------------------------------------------


async def _render_estimation_form(container: AppContainer, deadline: Deadline) -> None:
    """Show scaffold-aware effort estimation dialog."""
    scaffold: EstimationScaffold = await get_deadline_scaffold(
        container,
        deadline.deadline_type,  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
        course_id=deadline.course_id,  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
    )  # pyright: ignore[reportUnknownArgumentType]

    with ui.dialog() as dialog, ui.card().classes("w-96 p-4"):
        ui.label(f"Estimate: {deadline.name}").classes("font-bold text-lg")  # pyright: ignore[reportUnknownMemberType]
        ui.label(f"Scaffold: {scaffold.value}").classes("text-xs text-gray-400")  # pyright: ignore[reportUnknownMemberType]

        total_input = ui.number("Total Hours", value=0.0, min=0.0, step=0.5).classes("w-full")

        breakdown_inputs: dict[str, ui.number] = {}
        intention_input: ui.textarea | None = None

        if scaffold == "full":  # pyright: ignore[reportUnknownMemberType]
            ui.label("Breakdown").classes("font-semibold mt-2")
            for cat in _BREAKDOWN_CATEGORIES:
                inp = ui.number(f"{cat}:", value=0.0, min=0.0, step=0.25)
                breakdown_inputs[cat] = inp.classes("w-full")
            intention_input = ui.textarea("Implementation plan").classes("w-full mt-2")

        elif scaffold == "minimal":  # pyright: ignore[reportUnknownMemberType]
            show_breakdown = ui.switch("Show breakdown", value=False)

            @show_breakdown.on("update:model-value")  # pyright: ignore[reportCallIssue, reportUntypedFunctionDecorator]
            def _toggle(e: object) -> None:  # pyright: ignore[reportUnusedFunction]
                breakdown_col.set_visibility(show_breakdown.value)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]

            with ui.column().classes("w-full") as breakdown_col:
                breakdown_col.set_visibility(False)
                for cat in _BREAKDOWN_CATEGORIES:
                    inp = ui.number(f"{cat}:", value=0.0, min=0.0, step=0.25)
                    breakdown_inputs[cat] = inp.classes("w-full")

        # scaffold == "open" → just total_input, already rendered

        with ui.row().classes("w-full justify-end mt-4 gap-2"):

            async def _submit() -> None:
                hours = float(total_input.value or 0)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                if hours <= 0:
                    ui.notify("Enter estimated hours.", type="warning")
                    return
                bd = (
                    {k: float(v.value or 0) for k, v in breakdown_inputs.items()}  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                    if breakdown_inputs
                    else None
                )
                intent = intention_input.value if intention_input else None  # pyright: ignore[reportUnknownMemberType]
                _set_estimate_draft(
                    {
                        "deadline_id": deadline.id,  # pyright: ignore[reportUnknownMemberType]
                        "predicted_hours": hours,
                    }
                )
                await estimate_effort(
                    container,
                    deadline_id=deadline.id,  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
                    course_id=deadline.course_id,  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
                    predicted_hours=hours,
                    breakdown=bd,
                    intention=str(intent) if intent else None,
                )  # pyright: ignore[reportUnknownArgumentType]
                ui.notify("Estimate saved!", type="positive")
                dialog.close()
                _deadline_list.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

            ui.button("Save", on_click=_submit).props("color=primary")
            ui.button("Cancel", on_click=dialog.close).props("flat")

    dialog.open()


# --- Timer display -----------------------------------------------------------


def _render_timer_display() -> None:
    """Show elapsed time for the active timer, updating every second."""
    timer_label = ui.label("⏱ 00:00:00").classes("text-lg font-mono text-primary mt-1")
    start_time = datetime.now(UTC)

    def _update_display() -> None:
        elapsed = datetime.now(UTC) - start_time
        total_secs = int(elapsed.total_seconds())
        h, remainder = divmod(total_secs, 3600)
        m, s = divmod(remainder, 60)
        timer_label.text = f"⏱ {h:02d}:{m:02d}:{s:02d}"

    ui.timer(1, _update_display)


# --- Reflection form ---------------------------------------------------------


async def _render_reflection_form(container: AppContainer, deadline: Deadline) -> None:
    """Show post-deadline reflection dialog with empathetic feedback."""
    with ui.dialog() as dialog, ui.card().classes("w-96 p-4"):
        ui.label(f"Reflect: {deadline.name}").classes("font-bold text-lg")  # pyright: ignore[reportUnknownMemberType]

        actual_input = ui.number(
            "Actual Hours Spent",
            value=0.0,
            min=0.0,
            step=0.5,
        ).classes("w-full")
        reflection_input = ui.textarea("What went well? What could improve?").classes("w-full mt-2")
        feedback_area = ui.markdown("").classes("mt-2")

        async def _submit_reflection() -> None:
            actual = float(actual_input.value or 0)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
            text = str(reflection_input.value or "")  # pyright: ignore[reportUnknownMemberType]
            if actual <= 0:
                ui.notify("Enter actual hours.", type="warning")
                return

            draft = _get_estimate_draft()
            is_match = draft.get("deadline_id") == deadline.id  # pyright: ignore[reportUnknownMemberType]
            predicted = float(draft.get("predicted_hours", 0)) if is_match else None  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType, reportArgumentType]

            await reflect_on_deadline(
                container,
                deadline.id,  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
                predicted_hours=predicted,  # pyright: ignore[reportUnknownArgumentType]
                actual_hours=actual,
                reflection_text=text,
            )  # pyright: ignore[reportUnknownArgumentType]

            feedback = format_deadline_feedback(predicted, actual)  # pyright: ignore[reportUnknownArgumentType]
            feedback_area.set_content(feedback)  # pyright: ignore[reportUnknownMemberType]
            ui.notify("Reflection saved!", type="positive")
            _deadline_list.refresh()  # type: ignore[attr-defined]  # pyright: ignore[reportFunctionMemberAccess]

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Save", on_click=_submit_reflection).props("color=primary")
            ui.button("Cancel", on_click=dialog.close).props("flat")

    dialog.open()


# --- Calibration chart -------------------------------------------------------


async def _render_calibration_chart(container: AppContainer) -> None:
    """Render estimated vs actual hours as an ECharts bar chart."""
    metrics = await get_deadline_calibration(container)  # pyright: ignore[reportUnknownArgumentType]
    if not metrics:
        return

    domains = [m.domain for m in metrics]  # pyright: ignore[reportUnknownMemberType]
    errors = [m.mean_error for m in metrics]  # pyright: ignore[reportUnknownMemberType]
    abs_errors = [m.mean_absolute_error for m in metrics]  # pyright: ignore[reportUnknownMemberType]

    with ui.card().classes("w-full p-4 mt-6"):
        ui.label("Estimation Calibration").classes("text-lg font-bold mb-2")
        ui.echart(
            {
                "tooltip": {"trigger": "axis"},
                "legend": {"data": ["Mean Error", "Mean |Error|"]},
                "xAxis": {"type": "category", "data": domains},
                "yAxis": {"type": "value", "name": "Hours"},
                "series": [
                    {"name": "Mean Error", "type": "bar", "data": errors},
                    {"name": "Mean |Error|", "type": "bar", "data": abs_errors},
                ],
            }
        )
