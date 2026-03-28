"""NiceGUI application factory — wires DI lifecycle, routes, and logging."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import structlog
from nicegui import app, ui

from sophia.config import Settings
from sophia.domain.errors import AuthError
from sophia.gui.components.error_boundary import error_boundary
from sophia.gui.layout import app_shell
from sophia.gui.middleware.error_handler import handle_exception
from sophia.gui.middleware.health import (
    health,
    ready,
    reset_state,
    set_container,
    set_container_error,
)
from sophia.gui.pages.calibration import calibration_content
from sophia.gui.pages.chronos import chronos_content
from sophia.gui.pages.dashboard import dashboard_content
from sophia.gui.pages.lectures import lectures_content
from sophia.gui.pages.lectures_setup import lectures_setup_content
from sophia.gui.pages.review import review_content
from sophia.gui.pages.search import search_content
from sophia.gui.pages.settings import settings_content
from sophia.gui.pages.study import study_content
from sophia.gui.pages.topics import topics_content
from sophia.gui.services.chronos_service import sync_deadlines_from_gui
from sophia.gui.services.session_health import SessionHealthMonitor
from sophia.infra.di import create_app as create_di_container

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# Module-level reference for the DI exit stack and container
_exit_stack: contextlib.AsyncExitStack | None = None
_container: AppContainer | None = None
_health_monitor: SessionHealthMonitor | None = None
_startup_fn: object = None  # exposed for testing


def get_health_monitor() -> SessionHealthMonitor | None:
    """Return the session health monitor, or *None* if not started."""
    return _health_monitor


def configure(settings: Settings | None = None) -> None:
    """Configure the NiceGUI app: register lifecycle hooks, routes, and pages.

    Call this once before ``ui.run()``. It is idempotent — safe to call
    multiple times (hooks are re-registered, which NiceGUI handles).
    """
    resolved_settings = settings or Settings()

    # Health endpoints — plain FastAPI/Starlette routes
    app.add_route("/health", health)
    app.add_route("/ready", ready)

    # DI lifecycle
    async def _startup() -> None:
        global _exit_stack, _container, _health_monitor  # noqa: PLW0603
        reset_state()
        _exit_stack = contextlib.AsyncExitStack()
        try:
            _container = await _exit_stack.enter_async_context(
                create_di_container(resolved_settings),
            )
            set_container(_container)
            log.info(
                "gui_started",
                host=resolved_settings.gui_host,
                port=resolved_settings.gui_port,
            )
            _health_monitor = SessionHealthMonitor(
                _container.moodle,
                resolved_settings.session_keepalive_interval,
            )
            _health_monitor.start()
            if resolved_settings.auto_sync:
                asyncio.create_task(sync_deadlines_from_gui(_container))
        except AuthError as exc:
            log.warning("gui_auth_error", error=str(exc))
            set_container_error(str(exc))
        except Exception as exc:
            handle_exception(exc)
            set_container_error(f"Startup failed: {exc}")

    app.on_startup(_startup)  # type: ignore[reportUnknownMemberType]

    global _startup_fn  # noqa: PLW0603
    _startup_fn = _startup

    async def _shutdown() -> None:
        global _exit_stack, _container, _health_monitor  # noqa: PLW0603
        if _health_monitor is not None:
            await _health_monitor.stop()
            _health_monitor = None
        if _exit_stack is not None:
            await _exit_stack.aclose()
            _exit_stack = None
        _container = None
        reset_state()
        log.info("gui_stopped")

    app.on_shutdown(_shutdown)  # type: ignore[reportUnknownMemberType]

    # Register pages
    _register_pages()


def _register_pages() -> None:
    """Register all NiceGUI page routes."""

    @ui.page("/")
    async def dashboard_page() -> None:  # pyright: ignore[reportUnusedFunction]
        await app_shell(lambda: error_boundary(dashboard_content, page_name="Dashboard"))

    @ui.page("/study")
    async def study_page() -> None:  # pyright: ignore[reportUnusedFunction]
        await app_shell(lambda: error_boundary(study_content, page_name="Study"))

    @ui.page("/review")
    async def review_page() -> None:  # pyright: ignore[reportUnusedFunction]
        await app_shell(lambda: error_boundary(review_content, page_name="Review"))

    @ui.page("/search")
    async def search_page() -> None:  # pyright: ignore[reportUnusedFunction]
        await app_shell(lambda: error_boundary(search_content, page_name="Search"))

    @ui.page("/chronos")
    async def chronos_page() -> None:  # pyright: ignore[reportUnusedFunction]
        await app_shell(lambda: error_boundary(chronos_content, page_name="Chronos"))

    @ui.page("/calibration")
    async def calibration_page() -> None:  # pyright: ignore[reportUnusedFunction]
        await app_shell(lambda: error_boundary(calibration_content, page_name="Calibration"))

    @ui.page("/topics")
    async def topics_page() -> None:  # pyright: ignore[reportUnusedFunction]
        await app_shell(lambda: error_boundary(topics_content, page_name="Topics"))

    @ui.page("/lectures")
    async def lectures_page() -> None:  # pyright: ignore[reportUnusedFunction]
        await app_shell(lambda: error_boundary(lectures_content, page_name="Lectures"))

    @ui.page("/lectures/setup")
    async def lectures_setup_page() -> None:  # pyright: ignore[reportUnusedFunction]
        await app_shell(lambda: error_boundary(lectures_setup_content, page_name="Lecture Setup"))

    @ui.page("/settings")
    async def settings_page() -> None:  # pyright: ignore[reportUnusedFunction]
        await app_shell(lambda: error_boundary(settings_content, page_name="Settings"))


def run(settings: Settings | None = None) -> None:
    """Configure and start the NiceGUI server.

    Called by the ``sophia gui launch`` CLI command.
    """
    resolved = settings or Settings()
    configure(resolved)
    ui.run(  # type: ignore[reportUnknownMemberType]
        host=resolved.gui_host,
        port=resolved.gui_port,
        title="Sophia",
        reload=resolved.gui_reload,
        show=False,
        storage_secret="sophia-gui-storage",
    )
