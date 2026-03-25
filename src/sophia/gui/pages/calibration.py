"""Calibration dashboard — confidence scatter, blind spots, mastery heatmap."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

import structlog
from nicegui import app, ui

from sophia.gui.components.chart_table import chart_with_table
from sophia.gui.services.calibration_service import (
    build_blind_spot_chart_data,
    build_confidence_scatter_data,
    build_mastery_heatmap_data,
    compute_tier_progression,
    get_blind_spot_topics,
    get_calibration_ratings,
    get_study_sessions_for_topic,
)
from sophia.gui.state.storage_map import (
    GENERAL_APP_CONTAINER,
    TAB_CALIBRATION_COURSE_FILTER,
    USER_CURRENT_COURSE,
)

if TYPE_CHECKING:
    from sophia.domain.models import ConfidenceRating, StudySession
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# --- Constants ---------------------------------------------------------------

_OVERCONFIDENT_THRESHOLD: Final = 0.2
_DANGEROUS_THRESHOLD: Final = 0.3
_TIER_THRESHOLDS: Final[dict[str, float]] = {
    "cued": 0.4,
    "explain": 0.7,
    "transfer": 1.0,
}
_TIER_Y_MAP: Final[dict[str, int]] = {"cued": 0, "explain": 1, "transfer": 2}

_SOCRATIC_OBSERVATION: Final = (
    "You've been at {tier} for {topic} for {count} session(s). "
    "Students typically transition after 3-7 sessions at 80%+ accuracy. "
    "Your average: {avg:.0%}."
)
_SOCRATIC_QUESTION: Final = (
    "What do you think is keeping your accuracy at this level? "
    "Is it specific subtopics, or general uncertainty?"
)

_MAX_FEEDBACK_TOPICS: Final = 5
_TIER_Y_REVERSE: Final[dict[int, str]] = {0: "cued", 1: "explain", 2: "transfer"}


# --- Row extraction helpers (pure, tested) -----------------------------------


def extract_scatter_rows(chart: dict[str, Any]) -> list[list[str]]:
    """Extract [predicted, actual] rows from a scatter chart config."""
    series = chart.get("series", [{}])
    data = series[0].get("data", []) if series else []  # pyright: ignore[reportUnknownVariableType]
    return [[f"{pt[0]:.2f}", f"{pt[1]:.2f}"] for pt in data if len(pt) >= 2]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def extract_bar_rows(chart: dict[str, Any]) -> list[list[str]]:
    """Extract [label, value] rows from a bar chart config."""
    labels = chart.get("yAxis", {}).get("data") or chart.get("xAxis", {}).get("data") or []  # pyright: ignore[reportUnknownVariableType]
    series = chart.get("series", [{}])
    values = series[0].get("data", []) if series else []  # pyright: ignore[reportUnknownVariableType]
    return [[str(label), str(v)] for label, v in zip(labels, values, strict=False)]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def extract_line_rows(chart: dict[str, Any]) -> list[list[str]]:
    """Extract [x, y] rows from a line chart config."""
    x_data = chart.get("xAxis", {}).get("data", [])
    series = chart.get("series", [{}])
    y_data = series[0].get("data", []) if series else []  # pyright: ignore[reportUnknownVariableType]
    return [[str(x), f"{y:.2f}"] for x, y in zip(x_data, y_data, strict=False)]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def extract_heatmap_rows(chart: dict[str, Any]) -> list[list[str]]:
    """Extract [topic, course, score] rows from a heatmap chart config."""
    x_labels = chart.get("xAxis", {}).get("data", [])
    y_labels = chart.get("yAxis", {}).get("data", [])
    series = chart.get("series", [{}])
    data = series[0].get("data", []) if series else []  # pyright: ignore[reportUnknownVariableType]
    rows: list[list[str]] = []
    for pt in data:  # pyright: ignore[reportUnknownVariableType]
        if len(pt) >= 3:  # pyright: ignore[reportUnknownArgumentType]
            xi, yi = int(pt[0]), int(pt[1])  # pyright: ignore[reportUnknownArgumentType]
            topic = x_labels[xi] if xi < len(x_labels) else str(xi)
            course = y_labels[yi] if yi < len(y_labels) else str(yi)
            rows.append([str(topic), str(course), f"{pt[2]:.2f}"])
    return rows


def extract_tier_rows(chart: dict[str, Any]) -> list[list[str]]:
    """Extract [session, tier_name] rows from a tier progression chart."""
    x_data = chart.get("xAxis", {}).get("data", [])
    series = chart.get("series", [{}])
    y_data = series[0].get("data", []) if series else []  # pyright: ignore[reportUnknownVariableType]
    return [
        [str(x), _TIER_Y_REVERSE.get(int(y), str(y))]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        for x, y in zip(x_data, y_data, strict=False)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    ]


# --- Storage helpers ---------------------------------------------------------


def _get_course_filter() -> int | None:  # pyright: ignore[reportUnusedFunction]
    return app.storage.tab.get(TAB_CALIBRATION_COURSE_FILTER)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportReturnType]


def _set_course_filter(value: int | None) -> None:  # pyright: ignore[reportUnusedFunction]
    app.storage.tab[TAB_CALIBRATION_COURSE_FILTER] = value  # pyright: ignore[reportUnknownMemberType]


# --- Pure helpers ------------------------------------------------------------


def get_current_tier(score: float | None) -> str:
    """Map a score (0-1) to a difficulty tier name."""
    if score is None or score < _TIER_THRESHOLDS["cued"]:
        return "cued"
    if score < _TIER_THRESHOLDS["explain"]:
        return "explain"
    return "transfer"


def build_calibration_trend_data(ratings: list[ConfidenceRating]) -> dict[str, Any]:
    """Build ECharts line config for calibration error trend over time."""
    rated = sorted(
        [r for r in ratings if r.actual is not None],
        key=lambda r: r.rated_at,
    )
    if not rated:
        return {"series": [{"data": []}]}

    x_data = list(range(1, len(rated) + 1))
    y_data = [abs(r.calibration_error or 0.0) for r in rated]

    return {
        "title": {
            "text": "Calibration Error Trend",
            "left": "center",
            "textStyle": {"fontSize": 14},
        },
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": x_data, "name": "Rating #"},
        "yAxis": {"type": "value", "name": "Abs. Error", "min": 0, "max": 1},
        "series": [
            {
                "name": "Calibration Error",
                "type": "line",
                "data": y_data,
                "smooth": True,
                "lineStyle": {"color": "#5470c6"},
                "itemStyle": {"color": "#5470c6"},
            }
        ],
    }


def build_tier_progression_chart(progression: list[dict[str, Any]], topic: str) -> dict[str, Any]:
    """Build ECharts line config for difficulty tier progression."""
    if not progression:
        return {"series": [{"data": []}]}

    x_data = [p["session"] for p in progression]
    y_data = [_TIER_Y_MAP.get(p["tier"], 0) for p in progression]

    return {
        "title": {
            "text": f"Tier Progression: {topic}",
            "left": "center",
            "textStyle": {"fontSize": 14},
        },
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": x_data, "name": "Session"},
        "yAxis": {
            "type": "value",
            "name": "Tier",
            "min": 0,
            "max": 2,
            "axisLabel": {"formatter": "{value}"},
            "splitNumber": 2,
        },
        "series": [
            {
                "name": "Tier",
                "type": "line",
                "data": y_data,
                "step": "middle",
                "lineStyle": {"color": "#91cc75"},
                "itemStyle": {"color": "#91cc75"},
            }
        ],
    }


def format_socratic_feedback(topic: str, tier: str, session_count: int, avg_score: float) -> str:
    """Build Socratic observation + question text. Never prescriptive."""
    observation = _SOCRATIC_OBSERVATION.format(
        tier=tier.upper(),
        topic=topic,
        count=session_count,
        avg=avg_score,
    )
    return f"{observation}\n\n{_SOCRATIC_QUESTION}"


# --- Entry point -------------------------------------------------------------


def calibration_content() -> None:
    """Public entry point for the calibration dashboard page."""
    container = app.storage.general.get(GENERAL_APP_CONTAINER)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    if container is None:
        ui.label("Application not initialized.").classes("text-red-500")
        return

    course_id: int | None = app.storage.user.get(USER_CURRENT_COURSE)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType, reportAssignmentType]
    if course_id is None:
        ui.label("Select a course from the Dashboard to begin.").classes("text-gray-500")
        return

    _render_header()
    _charts(container, course_id)  # pyright: ignore[reportUnusedCoroutine, reportUnknownArgumentType]


# --- Header ------------------------------------------------------------------


def _render_header() -> None:
    with ui.row().classes("w-full items-center justify-between mb-4"):
        ui.label("Calibration").classes("text-2xl font-bold")


# --- Chart grid (refreshable) -----------------------------------------------


@ui.refreshable
async def _charts(container: AppContainer, course_id: int) -> None:  # pyright: ignore[reportUnknownParameterType]
    """Main chart grid — fetches data and renders all five visualisations."""
    ratings = await get_calibration_ratings(container, course_id)  # pyright: ignore[reportUnknownArgumentType]

    if not ratings:
        ui.label("No calibration data yet — complete a study session to see insights.").classes(
            "text-gray-400 italic mt-8 text-center w-full"
        )
        return

    blind_spots = await get_blind_spot_topics(container, course_id)  # pyright: ignore[reportUnknownArgumentType]

    with ui.grid(columns=2).classes("w-full gap-4"):
        # Chart 1: Confidence Scatter
        with ui.card().classes("col-span-1"):
            _render_confidence_scatter(ratings)

        # Chart 2: Blind Spots
        with ui.card().classes("col-span-1"):
            _render_blind_spots(ratings)

        # Chart 3: Calibration Error Trend
        with ui.card().classes("col-span-2"):
            _render_calibration_trend(ratings)

        # Chart 4: Topic Mastery Heatmap
        with ui.card().classes("col-span-2"):
            _render_mastery_heatmap(ratings)

    # Chart 5: Tier Progression (per blind-spot topic)
    if blind_spots:
        ui.label("Difficulty Tier Progression").classes("text-xl font-semibold mt-6 mb-2")
        for bs in blind_spots[:3]:
            await _render_tier_progression(container, course_id, bs.topic)

    # Socratic feedback section
    ui.separator().classes("my-4")
    ui.label("Desirable Difficulty Insights").classes("text-xl font-semibold mb-2")
    await _render_difficulty_feedback(container, course_id, ratings)


# --- Individual chart renderers ----------------------------------------------


def _render_confidence_scatter(ratings: list[ConfidenceRating]) -> None:
    """Predicted vs actual scatter — highlights over/under-confidence."""
    scatter_data = build_confidence_scatter_data(ratings)
    series_data = scatter_data.get("series", [{}])
    has_data = series_data and series_data[0].get("data")

    if has_data:
        chart_with_table(
            scatter_data,
            headers=["Predicted", "Actual"],
            rows=extract_scatter_rows(scatter_data),
            chart_id="confidence-scatter",
            classes="w-full h-64",
        )
    else:
        ui.label("No confidence vs actual data available.").classes("text-gray-400 italic")


def _render_blind_spots(ratings: list[ConfidenceRating]) -> None:
    """Horizontal bar chart of topics where student is overconfident."""
    chart_data = build_blind_spot_chart_data(ratings)
    series = chart_data.get("series", [{}])
    has_data = series and series[0].get("data")

    if has_data:
        chart_with_table(
            chart_data,
            headers=["Topic", "Overconfidence"],
            rows=extract_bar_rows(chart_data),
            chart_id="blind-spots",
            classes="w-full h-64",
        )
    else:
        ui.label("No blind spots detected — good calibration!").classes("text-green-500 italic")


def _render_calibration_trend(ratings: list[ConfidenceRating]) -> None:
    """Line chart of absolute calibration error over time."""
    trend_data = build_calibration_trend_data(ratings)
    series = trend_data.get("series", [{}])
    has_data = series and series[0].get("data")

    if has_data:
        chart_with_table(
            trend_data,
            headers=["Rating #", "Abs. Error"],
            rows=extract_line_rows(trend_data),
            chart_id="calibration-trend",
            classes="w-full h-48",
        )
    else:
        ui.label("Not enough data for trend analysis.").classes("text-gray-400 italic")


def _render_mastery_heatmap(ratings: list[ConfidenceRating]) -> None:
    """Heatmap of actual scores across topics and courses."""
    heatmap_data = build_mastery_heatmap_data(ratings)
    series = heatmap_data.get("series", [{}])
    has_data = series and series[0].get("data")

    if has_data:
        chart_with_table(
            heatmap_data,
            headers=["Topic", "Course", "Score"],
            rows=extract_heatmap_rows(heatmap_data),
            chart_id="mastery-heatmap",
            classes="w-full h-64",
        )
    else:
        ui.label("No mastery data available.").classes("text-gray-400 italic")


async def _render_tier_progression(
    container: AppContainer,  # pyright: ignore[reportUnknownParameterType]
    course_id: int,
    topic: str,
) -> None:
    """Step chart showing cued → explain → transfer progression for a topic."""
    sessions: list[StudySession] = await get_study_sessions_for_topic(container, course_id, topic)  # pyright: ignore[reportUnknownArgumentType]
    progression = compute_tier_progression(sessions)
    chart_data = build_tier_progression_chart(progression, topic)
    series = chart_data.get("series", [{}])
    has_data = series and series[0].get("data")

    if has_data:
        with ui.card().classes("w-full mb-2"):
            chart_with_table(
                chart_data,
                headers=["Session", "Tier"],
                rows=extract_tier_rows(chart_data),
                chart_id=f"tier-progression-{topic}",
                classes="w-full h-48",
            )
    else:
        ui.label(f"No session data for {topic}.").classes("text-gray-400 italic text-sm")


# --- Socratic difficulty feedback --------------------------------------------


async def _render_difficulty_feedback(
    container: AppContainer,  # pyright: ignore[reportUnknownParameterType]
    course_id: int,
    ratings: list[ConfidenceRating],
) -> None:
    """Render Socratic observations about tier stagnation per topic.

    Shows up to 5 topics where the student has actual performance data,
    with non-prescriptive prompts encouraging self-reflection.
    """
    topics_shown = 0
    for rating in ratings:
        if rating.actual is None:
            continue

        sessions: list[StudySession] = await get_study_sessions_for_topic(
            container,
            course_id,
            rating.topic,
        )  # pyright: ignore[reportUnknownArgumentType]
        if not sessions:
            continue

        scores = [s.post_test_score for s in sessions if s.post_test_score is not None]
        if not scores:
            continue

        avg_score = sum(scores) / len(scores)
        tier = get_current_tier(avg_score)
        feedback = format_socratic_feedback(rating.topic, tier, len(sessions), avg_score)

        with ui.card().classes("w-full mb-2 p-4"):
            with ui.row().classes("items-center gap-2 mb-2"):
                ui.label(rating.topic).classes("font-semibold")
                color = {"cued": "red", "explain": "orange", "transfer": "green"}.get(tier, "grey")
                ui.badge(tier.upper(), color=color).classes("text-xs")
            ui.markdown(feedback).classes("text-sm text-gray-700")

        topics_shown += 1
        if topics_shown >= _MAX_FEEDBACK_TOPICS:
            break

    if topics_shown == 0:
        ui.label("Complete more study sessions to see difficulty insights.").classes(
            "text-gray-400 italic"
        )
