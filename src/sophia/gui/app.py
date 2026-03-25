"""NiceGUI application factory — wires DI lifecycle, routes, and logging."""

from __future__ import annotations

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
from sophia.gui.pages.dashboard import dashboard_content
from sophia.infra.di import create_app as create_di_container

if TYPE_CHECKING:
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

# Module-level reference for the DI exit stack and container
_exit_stack: contextlib.AsyncExitStack | None = None
_container: AppContainer | None = None


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
    @app.on_startup  # type: ignore[reportUnknownMemberType]
    async def _startup() -> None:  # pyright: ignore[reportUnusedFunction]
        global _exit_stack, _container  # noqa: PLW0603
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
        except AuthError as exc:
            log.warning("gui_auth_error", error=str(exc))
            set_container_error(str(exc))
        except Exception as exc:
            handle_exception(exc)
            set_container_error(f"Startup failed: {exc}")

    @app.on_shutdown  # type: ignore[reportUnknownMemberType]
    async def _shutdown() -> None:  # pyright: ignore[reportUnusedFunction]
        global _exit_stack, _container  # noqa: PLW0603
        if _exit_stack is not None:
            await _exit_stack.aclose()
            _exit_stack = None
        _container = None
        reset_state()
        log.info("gui_stopped")

    # Register pages
    _register_pages()


def _register_pages() -> None:
    """Register all NiceGUI page routes."""

    @ui.page("/")
    def dashboard_page() -> None:  # pyright: ignore[reportUnusedFunction]
        app_shell(lambda: error_boundary(dashboard_content, page_name="Dashboard"))

    @ui.page("/study")
    def study_page() -> None:  # pyright: ignore[reportUnusedFunction]
        app_shell(lambda: error_boundary(_study_placeholder, page_name="Study"))

    @ui.page("/review")
    def review_page() -> None:  # pyright: ignore[reportUnusedFunction]
        app_shell(lambda: error_boundary(_review_placeholder, page_name="Review"))

    @ui.page("/search")
    def search_page() -> None:  # pyright: ignore[reportUnusedFunction]
        app_shell(lambda: error_boundary(_search_placeholder, page_name="Search"))

    @ui.page("/chronos")
    def chronos_page() -> None:  # pyright: ignore[reportUnusedFunction]
        app_shell(lambda: error_boundary(_chronos_placeholder, page_name="Chronos"))

    @ui.page("/calibration")
    def calibration_page() -> None:  # pyright: ignore[reportUnusedFunction]
        app_shell(
            lambda: error_boundary(_calibration_placeholder, page_name="Calibration"),
        )


def _study_placeholder() -> None:
    ui.label("Study").classes("text-2xl font-bold")
    ui.label("Study features coming soon.").classes("text-gray-500 mt-2")


def _review_placeholder() -> None:
    ui.label("Review").classes("text-2xl font-bold")
    ui.label("Review features coming soon.").classes("text-gray-500 mt-2")


def _search_placeholder() -> None:
    ui.label("Search").classes("text-2xl font-bold")
    ui.label("Search features coming soon.").classes("text-gray-500 mt-2")


def _chronos_placeholder() -> None:
    ui.label("Chronos").classes("text-2xl font-bold")
    ui.label("Deadline tracking coming soon.").classes("text-gray-500 mt-2")


def _calibration_placeholder() -> None:
    ui.label("Calibration").classes("text-2xl font-bold")
    ui.label("Calibration features coming soon.").classes("text-gray-500 mt-2")


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
