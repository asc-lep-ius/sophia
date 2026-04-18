"""Course overview cards — per-course status snapshots for the Dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from nicegui import ui

from sophia.gui.services.overview_service import health_tooltip

if TYPE_CHECKING:
    from sophia.gui.services.overview_service import CourseSummary

# Health indicator styling
_HEALTH_COLORS: Final[dict[str, str]] = {
    "green": "#15803d",
    "yellow": "#b45309",
    "red": "#b91c1c",
}

_HEALTH_ICONS: Final[dict[str, str]] = {
    "green": "check_circle",
    "yellow": "warning",
    "red": "error",
}

_OVERDUE_COLOR: Final[str] = "#b91c1c"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_course_cards(
    summaries: list[CourseSummary],
    density: str,
    insights: list[str] | None = None,
) -> None:
    """Render course overview cards appropriate for the given density mode."""
    if not summaries:
        return

    if density == "focus":
        _render_course_card(summaries[0])
    elif density == "full":
        _render_cards_grid(summaries)
        if insights:
            _render_insights_section(insights)
    else:
        _render_cards_grid(summaries)


# ---------------------------------------------------------------------------
# Internal renderers
# ---------------------------------------------------------------------------


def _render_cards_grid(summaries: list[CourseSummary]) -> None:
    with ui.row().classes("w-full gap-4 flex-wrap mb-4"):
        for summary in summaries:
            with ui.column().classes("flex-1 min-w-[280px]"):
                _render_course_card(summary)


def _render_course_card(summary: CourseSummary) -> None:
    """Single course status card."""
    color = _HEALTH_COLORS.get(summary.health, _HEALTH_COLORS["green"])
    icon = _HEALTH_ICONS.get(summary.health, _HEALTH_ICONS["green"])
    tooltip_text = health_tooltip(summary)
    has_data = (
        summary.upcoming_count > 0
        or summary.overdue_count > 0
        or summary.blind_spot_count > 0
        or summary.hours_this_week > 0
        or summary.topics_rated > 0
    )

    card = ui.card().classes("w-full p-4")

    with card:
        # Header: health icon + course name
        with ui.row().classes("items-center gap-2 mb-2"):
            health_icon = ui.icon(icon).style(f"color: {color}").classes("text-xl")
            health_icon.tooltip(tooltip_text)
            ui.label(summary.course_name).classes("font-semibold")

        if not has_data:
            ui.label(
                "No data yet for this course. "
                "Sync deadlines or start a study session to see your progress."
            ).classes("text-xs text-gray-500 italic")
            return

        # Deadline row
        _render_deadline_row(summary)

        # Calibration row
        _render_calibration_row(summary)

        # Time row
        with ui.row().classes("items-center gap-2 mt-1"):
            ui.icon("schedule").classes("text-sm text-gray-400")
            ui.label(f"{summary.hours_this_week}h this week").classes("text-xs text-gray-600")

        # Topics row
        if summary.topics_total > 0:
            with ui.row().classes("items-center gap-2 mt-1"):
                ui.icon("topic").classes("text-sm text-gray-400")
                ui.label(f"{summary.topics_rated}/{summary.topics_total} topics rated").classes(
                    "text-xs text-gray-600"
                )


def _render_deadline_row(summary: CourseSummary) -> None:
    parts: list[str] = []
    if summary.upcoming_count > 0:
        parts.append(f"{summary.upcoming_count} upcoming")
    if summary.overdue_count > 0:
        parts.append(f"{summary.overdue_count} overdue")
    if not parts:
        parts.append("No deadlines")

    with ui.row().classes("items-center gap-2 mt-1"):
        ui.icon("event").classes("text-sm text-gray-400")
        label = ui.label(", ".join(parts)).classes("text-xs text-gray-600")
        if summary.overdue_count > 0:
            label.style(f"color: {_OVERDUE_COLOR}")


def _render_calibration_row(summary: CourseSummary) -> None:
    with ui.row().classes("items-center gap-2 mt-1"):
        ui.icon("tune").classes("text-sm text-gray-400")
        if summary.blind_spot_count > 0:
            noun = "blind spot" if summary.blind_spot_count == 1 else "blind spots"
            ui.label(f"{summary.blind_spot_count} {noun}").classes("text-xs text-gray-600")
        else:
            ui.label("No blind spots").classes("text-xs text-gray-600")


def _render_insights_section(insights: list[str]) -> None:
    """Cross-course insights — shown only in Full density mode."""
    if not insights:
        return

    with ui.column().classes("w-full gap-2 mt-2 mb-4"):
        for insight in insights:
            with (
                ui.card().classes("w-full p-3 border-l-4").style("border-left-color: #1d4ed8"),
                ui.row().classes("items-start gap-2"),
            ):
                ui.icon("lightbulb").classes("text-lg").style("color: #1d4ed8")
                ui.label(insight).classes("text-sm")
