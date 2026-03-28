"""Chronos history & chart sections — extracted from chronos.py to stay under 800 lines."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final, cast

import structlog
from nicegui import app, ui

from sophia.gui.components.chart_table import chart_with_table
from sophia.gui.services.chronos_service import (
    DayEffort,
    build_effort_chart_config,
    get_deadline_calibration,
    get_deadline_reflection,
    get_effort_distribution_data,
    get_past_deadlines,
)
from sophia.gui.state.storage_map import BROWSER_EFFORT_CAPACITY

if TYPE_CHECKING:
    from sophia.domain.models import Deadline
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# Constants duplicated from chronos.py to avoid circular imports

_DEADLINE_TYPE_COLORS: Final[dict[str, str]] = {
    "assignment": "green",
    "quiz": "blue",
    "checkmark": "teal",
    "exam": "red",
    "exam_registration": "orange",
}

_OUTCOME_FILTER_OPTIONS: Final[dict[str, str]] = {
    "all": "All",
    "on_time": "On Time",
    "late": "Late",
    "missed": "Missed",
}

OUTCOME_BADGE_COLORS: Final[dict[str, str]] = {
    "on_time": "positive",
    "late": "warning",
    "missed": "negative",
}


def _classify_deadline_outcome(
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


def _format_calibration_error(predicted: float | None, actual: float) -> str:
    """Format predicted vs actual into a calibration comparison."""
    if predicted is None:
        return "No estimate recorded — try predicting next time!"
    error = actual - predicted
    return (
        f"**Predicted: {predicted:.1f}h | Actual: {actual:.1f}h | Error: {error:.1f}h**\n\n"
        "What factors did you miss or overweight in your estimate?"
    )


def _build_effort_subtitle(days: list[DayEffort], *, capacity: float = 4.0) -> str:
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


# --- Effort distribution chart -----------------------------------------------

_DEFAULT_CAPACITY: Final = 4.0


def _get_capacity() -> float:
    """Read effort capacity from browser storage, defaulting to 4h/day."""
    try:
        val = app.storage.browser.get(BROWSER_EFFORT_CAPACITY, _DEFAULT_CAPACITY)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        return float(val)  # pyright: ignore[reportUnknownArgumentType]
    except (RuntimeError, TypeError, ValueError):
        return _DEFAULT_CAPACITY


async def render_effort_chart(container: AppContainer) -> None:
    """Render the effort distribution stacked bar chart with capacity overlay."""
    days = await get_effort_distribution_data(container)  # pyright: ignore[reportUnknownArgumentType]
    if not days:
        return

    capacity = _get_capacity()
    chart_config = build_effort_chart_config(days, capacity=capacity)
    subtitle = _build_effort_subtitle(days, capacity=capacity)

    with ui.card().classes("w-full p-4 mt-6"):
        ui.label("Effort Distribution").classes("text-lg font-bold mb-1")
        ui.label(subtitle).classes("text-sm text-gray-500 mb-3")

        all_names: list[str] = []
        seen: set[str] = set()
        for d in days:
            for name in d.deadline_efforts:
                if name not in seen:
                    all_names.append(name)
                    seen.add(name)
        has_unest = any(d.unestimated for d in days)
        headers = ["Date", *all_names]
        if has_unest:
            headers.append("Unestimated")
        headers.append("Total")

        rows: list[list[str]] = []
        for d in days:
            row = [d.date]
            for name in all_names:
                row.append(f"{d.deadline_efforts.get(name, 0.0):.1f}")
            if has_unest:
                row.append(", ".join(d.unestimated) if d.unestimated else "—")
            row.append(f"{d.total:.1f}")
            rows.append(row)

        chart_with_table(
            chart_config,
            headers=headers,
            rows=rows,
            chart_id="chronos-effort-distribution",
        )


# --- Past deadlines section --------------------------------------------------


async def render_past_deadlines_section(
    container: AppContainer,
    *,
    get_course_filter: object,
    render_reflection_form: object,
) -> None:
    """Show past deadlines with outcome badges, filtering, and expandable detail rows.

    Parameters ``get_course_filter`` and ``render_reflection_form`` are callables
    injected from the parent page to avoid circular imports.
    """
    course_filter = cast("int | None", get_course_filter())  # type: ignore[operator]
    past = await get_past_deadlines(
        container,
        course_id=course_filter,
    )

    with ui.expansion("Past Deadlines", icon="history").classes("w-full mt-6"):
        if not past:
            with ui.column().classes("w-full items-center py-8"):
                ui.icon("event_available", color="gray").classes("text-4xl")
                ui.label("No past deadlines yet").classes("text-gray-500 mt-2")
            return

        outcome_filter = ui.toggle(
            _OUTCOME_FILTER_OPTIONS,
            value="all",
        ).classes("mb-3")

        results_container = ui.column().classes("w-full")

        async def _refresh_past_list() -> None:
            results_container.clear()
            selected = str(outcome_filter.value)  # pyright: ignore[reportUnknownMemberType]
            sorted_past = sorted(past, key=lambda d: d.due_at, reverse=True)  # pyright: ignore[reportUnknownMemberType, reportUnknownLambdaType]

            visible_count = 0
            for deadline in sorted_past:
                reflection = await get_deadline_reflection(container, deadline.id)  # pyright: ignore[reportUnknownArgumentType, reportUnknownMemberType]
                has_reflection = reflection is not None
                outcome = _classify_deadline_outcome(
                    deadline.due_at,  # pyright: ignore[reportUnknownArgumentType]
                    completed_at=deadline.due_at if has_reflection else None,  # pyright: ignore[reportUnknownArgumentType]
                )

                if selected != "all" and outcome != selected:
                    continue
                visible_count += 1

                badge_color = OUTCOME_BADGE_COLORS.get(outcome, "gray")
                with results_container:
                    await _render_past_deadline_card(
                        container,
                        deadline,
                        outcome,
                        badge_color,
                        reflection,
                        render_reflection_form=render_reflection_form,
                    )  # pyright: ignore[reportUnknownArgumentType]

            if visible_count == 0:
                with results_container:
                    ui.label("No deadlines match this filter").classes("text-gray-500 text-sm py-4")

        outcome_filter.on_value_change(lambda _: _refresh_past_list())  # pyright: ignore[reportUnknownMemberType]
        await _refresh_past_list()


async def _render_past_deadline_card(
    container: AppContainer,
    deadline: Deadline,
    outcome: str,
    badge_color: str,
    reflection: dict[str, object] | None,
    *,
    render_reflection_form: object,
) -> None:
    """Render a single past deadline card with outcome badge and expandable details."""
    with ui.card().classes("w-full p-3 mb-2"):
        with ui.row().classes("w-full items-center justify-between"):
            with ui.row().classes("items-center gap-2"):
                ui.badge(
                    outcome.replace("_", " ").title(),
                    color=badge_color,
                ).classes("text-xs")
                type_color = _DEADLINE_TYPE_COLORS.get(deadline.deadline_type.value, "gray")  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                ui.badge(
                    deadline.deadline_type.value.upper(),  # pyright: ignore[reportUnknownMemberType]
                    color=type_color,
                ).classes("text-xs")
                ui.label(deadline.name).classes("font-bold")  # pyright: ignore[reportUnknownMemberType]
            with ui.row().classes("items-center gap-2"):
                ui.label(f"Due: {deadline.due_at.strftime('%b %d')}").classes(  # pyright: ignore[reportUnknownMemberType]
                    "text-sm text-gray-500"
                )
                ui.label(deadline.course_name).classes("text-sm text-gray-500")  # pyright: ignore[reportUnknownMemberType]

        # Expandable details: reflection + calibration
        if reflection:
            with ui.expansion("Details", icon="expand_more").classes("w-full mt-1"):
                reflection_text = str(reflection.get("reflection_text", ""))
                if reflection_text:
                    ui.label("Reflection").classes("font-semibold text-sm mt-1")
                    ui.label(reflection_text).classes("text-sm text-gray-600")

                predicted = reflection.get("predicted_hours")
                actual = reflection.get("actual_hours")
                pred_f = float(str(predicted)) if predicted is not None else None
                actual_f = float(str(actual)) if actual is not None else 0.0
                calibration_text = _format_calibration_error(pred_f, actual_f)
                ui.label("Calibration").classes("font-semibold text-sm mt-2")
                ui.markdown(calibration_text).classes("text-sm")
        else:
            with ui.row().classes("mt-1 gap-2"):

                async def _show_reflect(dl: Deadline = deadline) -> None:  # pyright: ignore[reportUnknownParameterType]
                    await render_reflection_form(container, dl)  # type: ignore[operator]  # pyright: ignore[reportUnknownArgumentType]

                ui.button(
                    "Add Reflection",
                    icon="psychology",
                    on_click=_show_reflect,
                ).props("flat dense")


# --- Calibration chart -------------------------------------------------------


async def render_calibration_chart(container: AppContainer) -> None:
    """Render estimated vs actual hours as an ECharts bar chart."""
    metrics = await get_deadline_calibration(container)  # pyright: ignore[reportUnknownArgumentType]
    if not metrics:
        return

    domains = [m.domain for m in metrics]  # pyright: ignore[reportUnknownMemberType]
    errors = [m.mean_error for m in metrics]  # pyright: ignore[reportUnknownMemberType]
    abs_errors = [m.mean_absolute_error for m in metrics]  # pyright: ignore[reportUnknownMemberType]

    with ui.card().classes("w-full p-4 mt-6"):
        ui.label("Estimation Calibration").classes("text-lg font-bold mb-2")
        chart_config = {
            "tooltip": {"trigger": "axis"},
            "legend": {"data": ["Mean Error", "Mean |Error|"]},
            "xAxis": {"type": "category", "data": domains},
            "yAxis": {"type": "value", "name": "Hours"},
            "series": [
                {"name": "Mean Error", "type": "bar", "data": errors},
                {"name": "Mean |Error|", "type": "bar", "data": abs_errors},
            ],
        }
        headers = ["Domain", "Mean Error", "Mean |Error|"]
        rows = [
            [str(d), f"{e:.2f}", f"{a:.2f}"]
            for d, e, a in zip(domains, errors, abs_errors, strict=False)
        ]
        chart_with_table(
            chart_config,
            headers=headers,
            rows=rows,
            chart_id="chronos-calibration",
        )
