"""Chronos deadlines page — scaffold-aware effort estimation & time tracking."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog
from nicegui import app, ui

from sophia.gui.middleware.health import get_container
from sophia.gui.pages.chronos_history import (
    render_calibration_chart,
    render_effort_chart,
    render_past_deadlines_section,
)
from sophia.gui.services.chronos_service import (
    DayEffort,
    SyncResult,
    estimate_effort,
    export_deadlines_ics,
    format_deadline_feedback,
    get_deadline_priority,
    get_deadline_scaffold,
    get_deadline_tracked_time,
    get_time_entries,
    get_upcoming_deadlines,
    mark_deadline_complete,
    record_manual_time_entry,
    reflect_on_deadline,
    start_deadline_timer,
    stop_deadline_timer,
    sync_deadlines_from_gui,
)
from sophia.gui.state.storage_map import (
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

OUTCOME_BADGE_COLORS: Final[dict[str, str]] = {
    "on_time": "positive",
    "late": "warning",
    "missed": "negative",
}

# Sync debounce flag — prevents concurrent syncs within the same tab
_sync_in_progress: bool = False


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


def format_calibration_error(predicted: float | None, actual: float) -> str:
    """Format predicted vs actual into a calibration comparison with metacognitive prompt."""
    if predicted is None:
        return "No estimate recorded — try predicting next time!"
    error = actual - predicted
    return (
        f"**Predicted: {predicted:.1f}h | Actual: {actual:.1f}h | Error: {error:.1f}h**\n\n"
        "What factors did you miss or overweight in your estimate?"
    )


def classify_deadline_outcome(
    due_at: datetime,
    *,
    completed_at: datetime | None = None,
    now: datetime | None = None,
) -> str:
    """Classify a deadline as 'on_time', 'late', or 'missed'."""
    if completed_at is not None:
        return "late" if completed_at > due_at else "on_time"
    if now is None:
        now = datetime.now(UTC)
    return "missed" if now > due_at else "on_time"


_TIME_SOURCE_ICONS: Final[dict[str, str]] = {
    "timer": "⏱️",
    "manual": "✏️",
}


def format_time_source(source: str) -> str:
    """Map a time entry source to its display icon."""
    return _TIME_SOURCE_ICONS.get(source, "📝")


def build_effort_subtitle(days: list[DayEffort], *, capacity: float = 4.0) -> str:
    """Agency-oriented subtitle highlighting the day with most free capacity."""
    if not days:
        return "No upcoming effort to distribute"
    best_date = ""
    best_free = 0.0
    for d in days:
        free = capacity - d.total
        if free > best_free:
            best_free = free
            best_date = d.date
    if best_free <= 0:
        return "All days are fully booked — consider re-prioritising"
    return f"You have ~{best_free:.1f} free hours on {best_date}"


# --- Storage helpers ---------------------------------------------------------


def _get_course_filter() -> int | None:
    try:
        val = app.storage.tab.get(TAB_CHRONOS_COURSE_FILTER, None)
        return int(val) if val else None
    except RuntimeError:
        return None


def _set_course_filter(course_id: int | None) -> None:
    try:
        app.storage.tab[TAB_CHRONOS_COURSE_FILTER] = course_id
    except RuntimeError:
        log.debug("set_course_filter_no_tab_storage")


def _get_active_timer() -> str:
    try:
        return app.storage.tab.get(TAB_CHRONOS_ACTIVE_TIMER, "")
    except RuntimeError:
        return ""


def _set_active_timer(deadline_id: str) -> None:
    try:
        app.storage.tab[TAB_CHRONOS_ACTIVE_TIMER] = deadline_id
    except RuntimeError:
        log.debug("set_active_timer_no_tab_storage")


def _get_estimate_draft() -> dict[str, object]:
    try:
        return app.storage.tab.get(TAB_CHRONOS_ESTIMATE_DRAFT, {})
    except RuntimeError:
        return {}


def _set_estimate_draft(draft: dict[str, object]) -> None:
    try:
        app.storage.tab[TAB_CHRONOS_ESTIMATE_DRAFT] = draft
    except RuntimeError:
        log.debug("set_estimate_draft_no_tab_storage")


def _get_current_course() -> int:
    try:
        return app.storage.user.get(USER_CURRENT_COURSE, 0)
    except RuntimeError:
        return 0


# --- Entry point -------------------------------------------------------------


async def chronos_content() -> None:
    """Main Chronos deadlines page — called by app_shell + error_boundary."""
    container = get_container()
    if container is None:
        ui.label("Application not initialized.").classes("text-red-700")
        return
    _render_header(container)
    await _deadline_list(container)
    await render_effort_chart(container)
    await render_past_deadlines_section(
        container,
        get_course_filter=_get_course_filter,
        render_reflection_form=_render_reflection_form,
    )
    await render_calibration_chart(container)


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

            _render_sync_button(container)
            _render_export_button(container)


def _render_sync_button(container: AppContainer) -> None:
    """Sync button with progress indicator, debounce, and error-specific notifications."""
    spinner = ui.spinner(size="sm").classes("hidden")
    progress = ui.linear_progress(size="xs").classes("hidden w-32")
    sync_btn = ui.button("Sync", icon="sync").props("flat dense")

    async def _on_sync() -> None:
        global _sync_in_progress  # noqa: PLW0603
        if _sync_in_progress:
            return
        _sync_in_progress = True
        sync_btn.disable()
        spinner.classes(remove="hidden")

        async def _progress(fraction: float, message: str) -> None:
            if fraction < 0:
                # Indeterminate phase
                spinner.classes(remove="hidden")
                progress.classes(add="hidden")
            else:
                spinner.classes(add="hidden")
                progress.classes(remove="hidden")
                progress.set_value(fraction)

        try:
            result = await sync_deadlines_from_gui(container, progress_callback=_progress)
            _handle_sync_result(result)
        finally:
            _sync_in_progress = False
            sync_btn.enable()
            spinner.classes(add="hidden")
            progress.classes(add="hidden")
            _deadline_list.refresh()  # type: ignore[attr-defined]

    sync_btn.on_click(_on_sync)


def _handle_sync_result(result: SyncResult) -> None:
    """Show error-specific notifications based on sync result status."""
    if result.status == "success":
        if result.deadline_count:
            ui.notify(
                f"Synced {result.deadline_count} deadlines \u2713",
                type="positive",
            )
        else:
            ui.notify("No deadlines found \u2014 check your TUWEL connection", type="warning")
    elif result.status == "auth_expired":
        ui.notify("Session expired \u2014 reconnect in Settings", type="warning")
    elif result.status == "network_error":
        ui.notify("Sync failed \u2014 check your connection", type="negative")
    else:
        ui.notify("Sync failed \u2014 check logs for details", type="negative")


def _render_export_button(container: AppContainer) -> None:
    """Export Calendar button — generates ICS and triggers browser download."""
    export_btn = ui.button("Export Calendar", icon="calendar_month").props("flat dense")

    async def _handle_ics_export() -> None:
        export_btn.disable()
        try:
            ics_content = await export_deadlines_ics(container)
            if not ics_content:
                ui.notify(
                    "No deadlines to export",
                    type="warning",
                )
                return
            ui.download(
                ics_content.encode("utf-8"),
                "deadlines.ics",
            )
        except Exception:
            log.exception("ics_export_ui_failed")
            ui.notify("Export failed", type="negative")
        finally:
            export_btn.enable()

    export_btn.on_click(_handle_ics_export)


def _on_course_filter_change(value: object) -> None:
    _set_course_filter(int(value) if value else None)
    _deadline_list.refresh()  # type: ignore[attr-defined]


# --- Deadline list -----------------------------------------------------------


@ui.refreshable  # type: ignore[misc]
async def _deadline_list(container: AppContainer) -> None:
    """Fetch and render sorted deadline cards."""
    course_filter = _get_course_filter()
    deadlines: list[Deadline] = await get_upcoming_deadlines(
        container,
        course_id=course_filter,
        horizon_days=_HORIZON_DAYS,
    )

    if not deadlines:

        async def _sync_from_empty() -> None:
            result = await sync_deadlines_from_gui(container)
            _handle_sync_result(result)
            _deadline_list.refresh()  # type: ignore[attr-defined]

        with ui.column().classes("w-full items-center py-12"):
            ui.icon("calendar_month", color="gray").classes("text-6xl")
            ui.label("No deadlines synced").classes("text-lg font-semibold text-gray-600 mt-4")
            ui.label(
                "Connect to TUWEL to import your assignments, quizzes, and exams. "
                "Sophia helps you plan with predict \u2192 act \u2192 reflect."
            ).classes("text-sm text-gray-500 text-center max-w-md mt-2")
            ui.button(
                "Sync from TUWEL",
                icon="sync",
                on_click=_sync_from_empty,
            ).props("color=primary").classes("mt-4")
        return

    # Sort by due date
    sorted_deadlines = sorted(deadlines, key=lambda d: d.due_at)

    for deadline in sorted_deadlines:
        await _render_deadline_card(container, deadline)


# --- Deadline card -----------------------------------------------------------


async def _render_deadline_card(container: AppContainer, deadline: Deadline) -> None:
    """Render a single deadline card with info, priority, and actions."""
    priority = await get_deadline_priority(deadline, container)
    tracked = await get_deadline_tracked_time(container, deadline.id)
    active_timer = _get_active_timer()

    with ui.card().classes("w-full p-4 mb-3"):
        # Top row: type badge + name + course
        with ui.row().classes("w-full items-center justify-between"):
            with ui.row().classes("items-center gap-2"):
                color = _DEADLINE_TYPE_COLORS.get(deadline.deadline_type.value, "gray")
                ui.badge(
                    deadline.deadline_type.value.upper(),
                    color=color,
                ).classes("text-xs")
                ui.label(deadline.name).classes("font-bold")

            ui.label(deadline.course_name).classes("text-sm text-gray-500")

        # Due date + progress
        with ui.row().classes("w-full items-center justify-between mt-2"):
            due_text = format_due_date(deadline.due_at)
            overdue = "overdue" in due_text
            due_cls = "text-sm text-red-500 font-bold" if overdue else "text-sm text-gray-600"
            ui.label(due_text).classes(due_cls)

            # Hours progress bar
            draft = _get_estimate_draft()
            is_match = draft.get("deadline_id") == deadline.id
            estimated = float(draft.get("predicted_hours", 0) if is_match else 0)
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

            async def _show_estimate(dl: Deadline = deadline) -> None:
                await _render_estimation_form(container, dl)

            ui.button("Estimate", icon="calculate", on_click=_show_estimate).props("flat dense")

            is_running = active_timer == deadline.id
            if is_running:

                async def _stop(dl: Deadline = deadline) -> None:
                    elapsed = await stop_deadline_timer(container, dl.id)
                    _set_active_timer("")
                    ui.notify(f"Stopped — {format_hours(elapsed)} tracked", type="positive")
                    _deadline_list.refresh()  # type: ignore[attr-defined]

                ui.button(
                    "Stop ⏹",
                    icon="stop",
                    on_click=_stop,
                ).props("flat dense color=negative").props('aria-label="Stop timer"')
            else:

                async def _start(dl: Deadline = deadline) -> None:
                    current = _get_active_timer()
                    if current and current != dl.id:
                        msg = "Another timer is already running. Stop it first."
                        ui.notify(msg, type="warning")
                        return
                    await start_deadline_timer(container, dl.id)
                    _set_active_timer(dl.id)
                    ui.notify("Timer started", type="positive")
                    _deadline_list.refresh()  # type: ignore[attr-defined]

                ui.button(
                    "Start Timer",
                    icon="play_arrow",
                    on_click=_start,
                ).props("flat dense").props('aria-label="Start timer"')

            # Log Time (manual entry)
            async def _show_log_time(dl: Deadline = deadline) -> None:
                await _render_log_time_dialog(container, dl)

            ui.button("Log Time", icon="edit", on_click=_show_log_time).props("flat dense")

            # Mark Complete
            async def _mark_complete(dl: Deadline = deadline) -> None:
                _predicted, actual, _feedback = await mark_deadline_complete(container, dl.id)
                await _render_reflection_form(container, dl, pre_filled_hours=actual)

            ui.button(
                "Mark Complete",
                icon="check_circle",
                on_click=_mark_complete,
            ).props("flat dense color=positive")

            # Reflection for any deadline (not just overdue)
            async def _show_reflect(dl: Deadline = deadline) -> None:
                await _render_reflection_form(container, dl)

            ui.button("Reflect", icon="psychology", on_click=_show_reflect).props("flat dense")

        # Timer display if active
        if active_timer == deadline.id:
            _render_timer_display()

        # Time entries log
        entries = await get_time_entries(container, deadline.id)
        if entries:
            with ui.column().classes("mt-2 gap-1"):
                for entry in entries:
                    icon = format_time_source(str(entry["source"]))
                    hours_text = format_hours(float(str(entry["hours"])))
                    note = str(entry["note"]) if entry.get("note") else ""
                    label = f"{icon} {hours_text}"
                    if note:
                        label += f" — {note}"
                    ui.label(label).classes("text-xs text-gray-500")


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
        deadline.deadline_type,
        course_id=deadline.course_id,
    )

    with ui.dialog() as dialog, ui.card().classes("w-96 p-4"):
        ui.label(f"Estimate: {deadline.name}").classes("font-bold text-lg")
        ui.label(f"Scaffold: {scaffold.value}").classes("text-xs text-gray-400")

        total_input = ui.number("Total Hours", value=0.0, min=0.0, step=0.5).classes("w-full")

        breakdown_inputs: dict[str, ui.number] = {}
        intention_input: ui.textarea | None = None

        if scaffold == "full":
            ui.label("Breakdown").classes("font-semibold mt-2")
            for cat in _BREAKDOWN_CATEGORIES:
                inp = ui.number(f"{cat}:", value=0.0, min=0.0, step=0.25)
                breakdown_inputs[cat] = inp.classes("w-full")
            intention_input = ui.textarea("Implementation plan").classes("w-full mt-2")

        elif scaffold == "minimal":
            show_breakdown = ui.switch("Show breakdown", value=False)

            @show_breakdown.on("update:model-value")
            def _toggle(e: object) -> None:
                breakdown_col.set_visibility(show_breakdown.value)

            with ui.column().classes("w-full") as breakdown_col:
                breakdown_col.set_visibility(False)
                for cat in _BREAKDOWN_CATEGORIES:
                    inp = ui.number(f"{cat}:", value=0.0, min=0.0, step=0.25)
                    breakdown_inputs[cat] = inp.classes("w-full")

        # scaffold == "open" → just total_input, already rendered

        with ui.row().classes("w-full justify-end mt-4 gap-2"):

            async def _submit() -> None:
                hours = float(total_input.value or 0)
                if hours <= 0:
                    ui.notify("Enter estimated hours.", type="warning")
                    return
                bd = (
                    {k: float(v.value or 0) for k, v in breakdown_inputs.items()}
                    if breakdown_inputs
                    else None
                )
                intent = intention_input.value if intention_input else None
                _set_estimate_draft(
                    {
                        "deadline_id": deadline.id,
                        "predicted_hours": hours,
                    }
                )
                await estimate_effort(
                    container,
                    deadline_id=deadline.id,
                    course_id=deadline.course_id,
                    predicted_hours=hours,
                    breakdown=bd,
                    intention=str(intent) if intent else None,
                )
                ui.notify("Estimate saved!", type="positive")
                dialog.close()
                _deadline_list.refresh()  # type: ignore[attr-defined]

            ui.button("Save", on_click=_submit).props("color=primary")
            ui.button("Cancel", on_click=dialog.close).props("flat")

    dialog.open()


# --- Timer display -----------------------------------------------------------


def _render_timer_display() -> None:
    """Show elapsed time for the active timer, updating every second."""
    with ui.element("div").props('aria-live="polite"'):
        timer_label = ui.label("\u23f1 00:00:00").classes("text-lg font-mono text-primary mt-1")
    start_time = datetime.now(UTC)

    def _update_display() -> None:
        elapsed = datetime.now(UTC) - start_time
        total_secs = int(elapsed.total_seconds())
        h, remainder = divmod(total_secs, 3600)
        m, s = divmod(remainder, 60)
        timer_label.text = f"⏱ {h:02d}:{m:02d}:{s:02d}"

    ui.timer(1, _update_display)


# --- Log Time dialog ---------------------------------------------------------

_MIN_LOG_HOURS: Final = 0.25


async def _render_log_time_dialog(container: AppContainer, deadline: Deadline) -> None:
    """Show dialog for manual time entry logging."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")

    with ui.dialog() as dialog, ui.card().classes("w-96 p-4"):
        ui.label(f"Log Time: {deadline.name}").classes("font-bold text-lg")

        hours_input = ui.number(
            "Hours",
            value=_MIN_LOG_HOURS,
            min=_MIN_LOG_HOURS,
            step=_MIN_LOG_HOURS,
        ).classes("w-full")
        note_input = ui.textarea("Note (optional)").classes("w-full mt-2")
        date_input = ui.date(value=today).classes("w-full mt-2")

        error_label = ui.label("").classes("text-red-500 text-xs mt-1")
        error_label.set_visibility(False)

        async def _submit_log_time() -> None:
            hours = float(hours_input.value or 0)
            if hours < _MIN_LOG_HOURS:
                error_label.text = f"Enter at least {_MIN_LOG_HOURS} hours"
                error_label.set_visibility(True)
                return
            error_label.set_visibility(False)
            note = str(note_input.value or "").strip() or None
            recorded_at = str(date_input.value or today)

            await record_manual_time_entry(
                container,
                deadline.id,
                hours,
                note=note,
                recorded_at=recorded_at,
            )
            ui.notify(f"Logged {format_hours(hours)}", type="positive")
            dialog.close()
            _deadline_list.refresh()  # type: ignore[attr-defined]

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Save", on_click=_submit_log_time).props("color=primary")
            ui.button("Cancel", on_click=dialog.close).props("flat")

    dialog.open()


# --- Reflection form ---------------------------------------------------------


async def _render_reflection_form(
    container: AppContainer,
    deadline: Deadline,
    *,
    pre_filled_hours: float | None = None,
) -> None:
    """Show post-deadline reflection dialog with empathetic feedback."""
    with ui.dialog() as dialog, ui.card().classes("w-96 p-4"):
        ui.label(f"Reflect: {deadline.name}").classes("font-bold text-lg")

        actual_input = ui.number(
            "Actual Hours Spent",
            value=pre_filled_hours or 0.0,
            min=0.0,
            step=0.5,
        ).classes("w-full")
        reflection_input = ui.textarea("What went well? What could improve?").classes("w-full mt-2")
        feedback_area = ui.markdown("").classes("mt-2")
        calibration_area = ui.markdown("").classes("mt-2")

        async def _submit_reflection() -> None:
            actual = float(actual_input.value or 0)
            text = str(reflection_input.value or "")
            if actual <= 0:
                ui.notify("Enter actual hours.", type="warning")
                return

            draft = _get_estimate_draft()
            is_match = draft.get("deadline_id") == deadline.id
            predicted = float(draft.get("predicted_hours", 0)) if is_match else None

            await reflect_on_deadline(
                container,
                deadline.id,
                predicted_hours=predicted,
                actual_hours=actual,
                reflection_text=text,
            )

            feedback = format_deadline_feedback(predicted, actual)
            feedback_area.set_content(feedback)
            calibration = format_calibration_error(predicted, actual)
            calibration_area.set_content(calibration)
            ui.notify("Reflection saved!", type="positive")
            _deadline_list.refresh()  # type: ignore[attr-defined]

        with ui.row().classes("w-full justify-end mt-4 gap-2"):
            ui.button("Save", on_click=_submit_reflection).props("color=primary")
            ui.button("Cancel", on_click=dialog.close).props("flat")

    dialog.open()
