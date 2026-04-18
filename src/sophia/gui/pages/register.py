"""TISS registration page — favorites, groups, and manual registration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Final

import structlog
from nicegui import ui

from sophia.domain.models import RegistrationStatus
from sophia.gui.middleware.health import get_container
from sophia.gui.services.registration_service import (
    RegisterResult,
    get_exam_dates,
    get_favorites,
    get_groups,
    get_registration_status,
    register_course,
)

if TYPE_CHECKING:
    from sophia.domain.models import FavoriteCourse, RegistrationGroup, TissExamDate
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# -- Constants ----------------------------------------------------------------

_TISS_DATE_FMT: Final = "%d.%m.%Y %H:%M"

_STATUS_COLORS: Final[dict[str, str]] = {
    "open": "green",
    "registered": "blue",
    "pending": "yellow",
    "full": "red",
    "closed": "gray",
    "failed": "red",
}

_REG_CHECK_ICON: Final = "check_circle"
_REG_MISSING_ICON: Final = "radio_button_unchecked"


# -- Pure helpers (testable) --------------------------------------------------


def status_badge_color(status: RegistrationStatus | str) -> str:
    """Map a RegistrationStatus to a badge color string."""
    return _STATUS_COLORS.get(str(status), "gray")


def format_countdown(
    registration_start: str | None,
    *,
    now: datetime | None = None,
) -> str:
    """Format time until registration opens.

    Returns 'Opens in Xd Yh Zm', 'Open now', or '' if no start time.
    """
    if not registration_start:
        return ""

    if now is None:
        now = datetime.now(UTC)

    try:
        opens_at = datetime.strptime(registration_start, _TISS_DATE_FMT).replace(tzinfo=UTC)
    except ValueError:
        return ""

    delta = opens_at - now
    total_seconds = int(delta.total_seconds())

    if total_seconds <= 0:
        return "Open now"

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    parts: list[str] = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or not parts:
        parts.append(f"{minutes}m")

    return f"Opens in {' '.join(parts)}"


def format_capacity(enrolled: int, capacity: int) -> str:
    """Format group capacity as 'enrolled/capacity'."""
    return f"{enrolled}/{capacity}"


# -- Page entry point ---------------------------------------------------------


async def register_content() -> None:
    """Main registration page content — called by app_shell + error_boundary."""
    container = get_container()
    if container is None:
        ui.label("Loading...").classes("text-gray-400")
        return

    _render_header()
    await _favorites_section(container)


# -- UI sections --------------------------------------------------------------


def _render_header() -> None:
    """Page header with title and refresh button."""
    with ui.row().classes("w-full items-center justify-between mb-4"):
        ui.label("Registration").classes("text-2xl font-bold")
        ui.button(
            "Refresh",
            icon="refresh",
            on_click=lambda: _favorites_section.refresh(),  # type: ignore[attr-defined]
        ).props("flat")


@ui.refreshable
async def _favorites_section(container: AppContainer) -> None:
    """Render TISS favorites with registration status badges."""
    result = await get_favorites(container)

    if result.status == "no_session":
        _render_no_session()
        return
    if result.status == "auth_expired":
        _render_auth_expired()
        return
    if result.status == "network_error":
        _render_network_error(result.error_message or "Cannot reach TISS")
        return
    if result.status == "error":
        _render_error(result.error_message or "Unknown error")
        return

    if not result.favorites:
        ui.label("No favorite courses found on TISS.").classes("text-gray-400 mt-4")
        return

    for fav in result.favorites:
        await _render_course_card(container, fav)


async def _render_course_card(container: AppContainer, fav: FavoriteCourse) -> None:
    """Render a single course with expandable details."""
    with ui.expansion(
        text=f"{fav.title} ({fav.course_number})",
    ).classes("w-full mb-2") as expansion:
        # Registration status badges in header
        with ui.row().classes("gap-2"):
            _reg_badge("LVA", fav.lva_registered)
            _reg_badge("Group", fav.group_registered)
            _reg_badge("Exam", fav.exam_registered)

        expansion.on("show", lambda c=container, f=fav: _load_course_details(c, f))


def _reg_badge(label: str, registered: bool) -> None:
    """Show a checkmark or empty circle badge for a registration type."""
    icon = _REG_CHECK_ICON if registered else _REG_MISSING_ICON
    color = "green" if registered else "gray"
    ui.chip(label, icon=icon, color=color).props("outline" if not registered else "")


async def _load_course_details(container: AppContainer, fav: FavoriteCourse) -> None:
    """Load and display course groups and exam dates when expanding."""
    from sophia.gui.services.registration_service import current_semester

    semester = current_semester()

    # Fetch registration status
    status_result = await get_registration_status(container, fav.course_number, semester)
    if status_result.status == "success" and status_result.target:
        target = status_result.target
        with ui.row().classes("gap-2 items-center mt-2"):
            badge_color = status_badge_color(target.status)
            ui.badge(target.status.value.upper(), color=badge_color)
            countdown = format_countdown(target.registration_start)
            if countdown:
                ui.label(countdown).classes("text-sm text-gray-500")

    # Fetch groups
    groups_result = await get_groups(container, fav.course_number, semester)
    if groups_result.status == "success" and groups_result.groups:
        _render_groups_table(groups_result.groups)
        _render_register_buttons(container, fav, semester, groups_result.groups)

    # Fetch exam dates
    exams = await get_exam_dates(container, fav.course_number)
    if exams:
        _render_exam_dates(exams)


def _render_groups_table(groups: list[RegistrationGroup]) -> None:
    """Render a table of available groups."""
    ui.label("Groups").classes("font-semibold mt-3 mb-1")
    columns = [
        {"name": "name", "label": "Group", "field": "name", "align": "left"},
        {"name": "day", "label": "Day", "field": "day"},
        {"name": "time", "label": "Time", "field": "time"},
        {"name": "capacity", "label": "Capacity", "field": "capacity"},
        {"name": "status", "label": "Status", "field": "status"},
    ]
    rows = [
        {
            "name": g.name,
            "day": g.day,
            "time": f"{g.time_start}–{g.time_end}",
            "capacity": format_capacity(g.enrolled, g.capacity),
            "status": g.status.value.upper(),
        }
        for g in groups
    ]
    ui.table(columns=columns, rows=rows, row_key="name").classes("w-full")


def _render_register_buttons(
    container: AppContainer,
    fav: FavoriteCourse,
    semester: str,
    groups: list[RegistrationGroup],
) -> None:
    """Render register buttons for each open group."""
    open_groups = [g for g in groups if g.status == RegistrationStatus.OPEN]
    if not open_groups:
        return

    ui.label("Register").classes("font-semibold mt-3 mb-1")
    for group in open_groups:
        ui.button(
            f"Register — {group.name}",
            icon="how_to_reg",
            on_click=lambda c=container, f=fav, s=semester, g=group: _confirm_registration(
                c,
                f.course_number,
                s,
                g,  # type: ignore[arg-type]
            ),
        ).props("outline")


async def _confirm_registration(
    container: AppContainer,
    course_number: str,
    semester: str,
    group: RegistrationGroup,
) -> None:
    """Show confirmation dialog before submitting registration."""
    with ui.dialog() as dialog, ui.card():
        ui.label("Confirm Registration").classes("text-lg font-bold")
        ui.label(f"Register for {group.name} ({group.day} {group.time_start}–{group.time_end})?")
        ui.label(f"Capacity: {format_capacity(group.enrolled, group.capacity)}")

        with ui.row().classes("w-full justify-end gap-2 mt-4"):
            ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat")
            ui.button(
                "Register",
                on_click=lambda: dialog.submit(True),
                color="primary",
            )

    confirmed = await dialog
    if not confirmed:
        return

    result = await register_course(container, course_number, semester, group_id=group.group_id)
    _show_registration_result(result)


def _show_registration_result(result: RegisterResult) -> None:
    """Show notification for registration result."""
    if result.status == "success" and result.registration_result:
        if result.registration_result.success:
            ui.notify(
                f"Registered: {result.registration_result.message}",
                type="positive",
            )
        else:
            ui.notify(
                f"Registration failed: {result.registration_result.message}",
                type="negative",
            )
    elif result.status == "auth_expired":
        ui.notify("Session expired — re-authenticate in Settings", type="warning")
    elif result.status == "no_session":
        ui.notify("Not logged in — authenticate in Settings", type="warning")
    else:
        ui.notify(
            f"Registration failed: {result.error_message or 'Unknown error'}",
            type="negative",
        )


def _render_exam_dates(exams: list[TissExamDate]) -> None:
    """Render exam date information."""
    ui.label("Exam Dates").classes("font-semibold mt-3 mb-1")
    for exam in exams:
        with ui.row().classes("gap-2 items-center"):
            ui.label(exam.title or "Exam").classes("font-medium")
            if exam.date_start:
                ui.label(exam.date_start).classes("text-sm text-gray-500")
            if exam.mode:
                ui.badge(exam.mode, color="blue").props("outline")


# -- Error state renderers ----------------------------------------------------


def _render_no_session() -> None:
    """Render message when TISS session is not available."""
    with ui.card().classes("w-full mt-4 p-4"):
        ui.icon("warning", color="orange").classes("text-3xl")
        ui.label("Not logged in to TISS").classes("text-lg font-semibold")
        ui.label("Run 'sophia auth login --tiss' or authenticate in Settings.")


def _render_auth_expired() -> None:
    """Render message when TISS session has expired."""
    with ui.card().classes("w-full mt-4 p-4"):
        ui.icon("error", color="red").classes("text-3xl")
        ui.label("Session expired — re-authenticate in Settings").classes("text-lg font-semibold")
        ui.button(
            "Go to Settings",
            icon="settings",
            on_click=lambda: ui.navigate.to("/settings"),
        ).props("outline")


def _render_network_error(message: str) -> None:
    """Render message when TISS is unreachable (network/VPN issue)."""
    with ui.card().classes("w-full mt-4 p-4"):
        ui.icon("wifi_off", color="orange").classes("text-3xl")
        ui.label("Cannot reach TISS").classes("text-lg font-semibold")
        ui.label("Check your internet connection or VPN.").classes("text-sm text-gray-500")
        with ui.expansion("Details").classes("w-full"):
            ui.label(message).classes("text-sm text-gray-500")
        ui.button(
            "Retry",
            icon="refresh",
            on_click=lambda: _favorites_section.refresh(),  # type: ignore[attr-defined]
        ).props("outline")


def _render_error(message: str) -> None:
    """Render an error message with retry button."""
    with ui.card().classes("w-full mt-4 p-4"):
        ui.icon("error", color="red").classes("text-3xl")
        ui.label("Something went wrong").classes("text-lg font-semibold")
        with ui.expansion("Details").classes("w-full"):
            ui.label(message).classes("text-sm text-gray-500")
        ui.button(
            "Retry",
            icon="refresh",
            on_click=lambda: _favorites_section.refresh(),  # type: ignore[attr-defined]
        ).props("outline")


# Countdown timer — refresh UI every 60s (does NOT poll TISS)
def _start_countdown_timer() -> None:
    """Create a UI timer that refreshes the favorites section periodically."""
    ui.timer(interval=60, callback=lambda: _favorites_section.refresh())  # type: ignore[attr-defined]
