"""Settings page — auth status, job observability, and configuration display."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from nicegui import app, ui

from sophia.adapters.auth import clear_session, load_session, session_path
from sophia.gui.middleware.health import get_container
from sophia.gui.pages.lectures import is_hermes_setup_complete
from sophia.gui.services.job_registry import JobEntry, JobRegistry
from sophia.gui.state.storage_map import USER_HERMES_SETUP_COMPLETE, USER_QUICKSTART_COMPLETED

if TYPE_CHECKING:
    from sophia.gui.services.session_health import SessionHealthMonitor
    from sophia.infra.di import AppContainer

log = structlog.get_logger()


# --- Deferred import to avoid circular dependency with app.py ----------------


def get_health_monitor() -> SessionHealthMonitor | None:
    """Proxy for ``sophia.gui.app.get_health_monitor``."""
    from sophia.gui.app import get_health_monitor as _get

    return _get()


# --- Pure helpers (tested directly) ------------------------------------------


def format_session_age(created_at: str, *, now: datetime | None = None) -> str:
    """Human-readable age from an ISO-8601 timestamp."""
    try:
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        ref = now or datetime.now(UTC)
        delta = ref - created
        total_minutes = int(delta.total_seconds() // 60)
        if total_minutes < 60:
            unit = "minute" if total_minutes == 1 else "minutes"
            return f"{total_minutes} {unit} ago"
        total_hours = total_minutes // 60
        if total_hours < 24:
            unit = "hour" if total_hours == 1 else "hours"
            return f"{total_hours} {unit} ago"
        total_days = total_hours // 24
        unit = "day" if total_days == 1 else "days"
        return f"{total_days} {unit} ago"
    except (ValueError, TypeError):
        return "unknown"


def health_status_label(monitor: SessionHealthMonitor | None) -> tuple[str, str]:
    """Return (status_text, tailwind_css_class) for the session health state."""
    if monitor is None:
        return "Not connected", "text-red-600"
    if monitor.is_healthy:
        return "Connected", "text-green-600"
    return "Session expired", "text-amber-600"


def hermes_setup_status(is_complete: bool) -> tuple[str, str, str]:
    """Return (label, icon, css_class) for Hermes setup state."""
    if is_complete:
        return "Configured", "check_circle", "text-green-600"
    return "Not configured", "pending", "text-gray-500"


# --- Job display helpers (tested directly) -----------------------------------

_STATUS_BADGES: dict[str, tuple[str, str]] = {
    "queued": ("gray", "hourglass_empty"),
    "running": ("blue", "sync"),
    "completed": ("green", "check_circle"),
    "failed": ("red", "error"),
    "cancelled": ("orange", "cancel"),
}


def job_status_badge(status: str) -> tuple[str, str, str]:
    """Return (label, color, icon) for a job status string."""
    color, icon = _STATUS_BADGES.get(status, ("gray", "help"))
    return status.capitalize(), color, icon


def format_elapsed(started_at: datetime | None) -> str:
    """Human-readable elapsed time from *started_at* until now."""
    if started_at is None:
        return "—"
    delta = datetime.now(UTC) - started_at
    total_minutes = int(delta.total_seconds() // 60)
    if total_minutes < 1:
        return "< 1m"
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_duration(
    started_at: datetime | None,
    completed_at: datetime | None,
) -> str:
    """Human-readable duration between two timestamps."""
    if started_at is None or completed_at is None:
        return "—"
    total_seconds = int((completed_at - started_at).total_seconds())
    if total_seconds < 0:
        return "—"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


# --- Logout action -----------------------------------------------------------


def perform_logout(container: AppContainer) -> None:
    """Clear session file and NiceGUI user storage, then redirect."""
    clear_session(session_path(container.settings.config_dir))
    app.storage.user.clear()
    ui.notify("Logged out successfully", type="positive")
    ui.navigate.to("/settings")
    log.info("user_logged_out")


# --- Page content ------------------------------------------------------------


async def settings_content() -> None:
    """Render the Settings page with auth, job status, and config sections."""
    container = get_container()
    if container is None:
        ui.label("Application not initialized.").classes("text-red-700")
        return

    ui.label("Settings").classes("text-2xl font-bold mb-4")

    _render_auth_section(container)
    _render_jobs_section()
    _render_config_section(container)
    _render_hermes_section()
    _render_quickstart_section()


def _render_auth_section(container: AppContainer) -> None:
    """Auth & Connection Status card."""
    with ui.card().classes("w-full mb-4"):
        ui.label("Auth & Connection Status").classes("text-lg font-semibold mb-2")
        ui.separator()

        monitor = get_health_monitor()
        status_text, status_css = health_status_label(monitor)

        with ui.row().classes("items-center gap-2 mt-2"):
            ui.icon("wifi" if monitor and monitor.is_healthy else "wifi_off").classes("text-xl")
            ui.label(status_text).classes(f"font-medium {status_css}")

        # Session age
        creds = load_session(session_path(container.settings.config_dir))
        if creds is not None:
            age = format_session_age(creds.created_at)
            ui.label(f"Session age: {age}").classes("text-sm text-gray-600 mt-1")
            ui.label("Services: TUWEL").classes("text-sm text-gray-600")
        else:
            ui.label(
                'Run "sophia auth login" in terminal to connect to TUWEL',
            ).classes("text-sm text-gray-500 mt-1 italic")

        # Logout button
        def _on_logout() -> None:
            with ui.dialog() as dialog, ui.card():
                ui.label("Are you sure you want to log out?").classes("mb-2")
                with ui.row().classes("gap-2"):
                    ui.button("Cancel", on_click=dialog.close)
                    ui.button(
                        "Log out",
                        on_click=lambda: (dialog.close(), perform_logout(container)),
                        color="red",
                    )
            dialog.open()

        ui.button("Log out", icon="logout", on_click=_on_logout).classes("mt-3").props(
            "outline",
        )


def _render_jobs_section() -> None:
    """Background Jobs card — active jobs, history, cancel actions."""
    with ui.card().classes("w-full mb-4"):
        ui.label("Background Jobs").classes("text-lg font-semibold mb-2")
        ui.separator()
        _jobs_content()


@ui.refreshable
def _jobs_content() -> None:
    """Refreshable inner content for the jobs section."""
    registry = JobRegistry()
    active = registry.get_active()
    history = registry.get_history()

    if not active and not history:
        with ui.row().classes("items-center gap-2 mt-2"):
            ui.icon("info").classes("text-xl text-gray-400")
            ui.label(
                "No background jobs yet. Jobs appear here when you sync "
                "deadlines, process lectures, or extract topics.",
            ).classes("text-sm text-gray-500 italic")
        return

    if active:
        ui.label("Active").classes("text-sm font-semibold text-gray-700 mt-2")
        for job in active:
            _render_active_job(registry, job)

    if history:
        ui.label("History").classes("text-sm font-semibold text-gray-700 mt-4")
        for job in history:
            _render_history_job(job)


def _render_active_job(registry: JobRegistry, job: JobEntry) -> None:
    """Render a single active (queued/running) job row."""
    label, color, icon = job_status_badge(job.status)
    with ui.row().classes("items-center gap-3 mt-2 w-full"):
        ui.icon(icon).classes(f"text-lg text-{color}-500")
        ui.label(job.name).classes("text-sm font-medium flex-1")
        ui.badge(label, color=color).props("outline")
        if job.status == "running":
            ui.linear_progress(value=job.progress).classes("w-24").props("rounded")
            ui.label(f"{job.progress:.0%}").classes("text-xs text-gray-500 w-10")
        elapsed = format_elapsed(job.started_at)
        ui.label(elapsed).classes("text-xs text-gray-400 w-16")

        def _cancel(jid: str = job.id) -> None:
            registry.cancel(jid)
            _jobs_content.refresh()  # type: ignore[attr-defined]

        ui.button(icon="close", on_click=_cancel).props("flat dense round size=sm").tooltip(
            "Cancel"
        )


def _render_history_job(job: JobEntry) -> None:
    """Render a single completed/failed/cancelled job row."""
    label, color, icon = job_status_badge(job.status)
    duration = format_duration(job.started_at, job.completed_at)
    timestamp = job.completed_at.strftime("%Y-%m-%d %H:%M") if job.completed_at else "—"

    if job.status == "failed" and job.error:
        with ui.expansion(text="").classes("w-full mt-1") as exp:
            with exp.add_slot("header"), ui.row().classes("items-center gap-3 w-full"):
                ui.icon(icon).classes(f"text-lg text-{color}-500")
                ui.label(job.name).classes("text-sm flex-1")
                ui.badge(label, color=color).props("outline")
                ui.label(duration).classes("text-xs text-gray-400 w-16")
                ui.label(timestamp).classes("text-xs text-gray-400")
            ui.label(job.error).classes("text-xs text-red-600 font-mono whitespace-pre-wrap")
        return

    with ui.row().classes("items-center gap-3 mt-2 w-full"):
        ui.icon(icon).classes(f"text-lg text-{color}-500")
        ui.label(job.name).classes("text-sm flex-1")
        ui.badge(label, color=color).props("outline")
        ui.label(duration).classes("text-xs text-gray-400 w-16")
        ui.label(timestamp).classes("text-xs text-gray-400")


def _render_config_section(container: AppContainer) -> None:
    """Configuration Display card."""
    settings = container.settings
    with ui.card().classes("w-full mb-4"):
        ui.label("Configuration").classes("text-lg font-semibold mb-2")
        ui.separator()

        _config_row("Data directory", str(settings.data_dir))
        _config_row("Config directory", str(settings.config_dir))
        _config_row("Keepalive interval", f"{settings.session_keepalive_interval}s")


def _render_hermes_section() -> None:
    """Hermes Lecture Pipeline configuration card."""
    is_complete = is_hermes_setup_complete()
    label, icon, css = hermes_setup_status(is_complete)

    with ui.card().classes("w-full mb-4"):
        ui.label("Lecture Pipeline (Hermes)").classes("text-lg font-semibold mb-2")
        ui.separator()

        with ui.row().classes("items-center gap-2 mt-2"):
            ui.icon(icon).classes(f"text-xl {css}")
            ui.label(label).classes(f"font-medium {css}")

        if is_complete:

            def _rerun() -> None:
                app.storage.user[USER_HERMES_SETUP_COMPLETE] = False
                ui.navigate.to("/lectures/setup")

            ui.button("Re-run Setup", icon="refresh", on_click=_rerun).classes("mt-3").props(
                "outline",
            )
        else:
            ui.button(
                "Run Setup",
                icon="play_arrow",
                on_click=lambda: ui.navigate.to("/lectures/setup"),
            ).classes("mt-3")


def _config_row(label: str, value: str) -> None:
    """Single key-value config display row."""
    with ui.row().classes("items-center gap-4 mt-2"):
        ui.label(label).classes("text-sm text-gray-500 w-40")
        ui.label(value).classes("text-sm font-mono")


def _render_quickstart_section() -> None:
    """Quickstart Wizard status and re-run option."""
    is_complete = app.storage.user.get(USER_QUICKSTART_COMPLETED, False)
    with ui.card().classes("w-full mb-4"):
        ui.label("Quickstart Wizard").classes("text-lg font-semibold mb-2")
        ui.separator()

        if is_complete:
            with ui.row().classes("items-center gap-2 mt-2"):
                ui.icon("check_circle").classes("text-xl text-green-600")
                ui.label("Completed").classes("font-medium text-green-600")

            def _rerun() -> None:
                app.storage.user[USER_QUICKSTART_COMPLETED] = False
                ui.navigate.to("/")

            ui.button("Re-run Quickstart", icon="refresh", on_click=_rerun).classes(
                "mt-3",
            ).props("outline")
        else:
            with ui.row().classes("items-center gap-2 mt-2"):
                ui.icon("pending").classes("text-xl text-gray-500")
                ui.label("Not yet completed").classes("text-sm text-gray-500")
