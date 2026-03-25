"""CLI command to launch the Sophia web GUI."""

from __future__ import annotations

from typing import Annotated

import cyclopts

from sophia.cli._output import get_console

app = cyclopts.App(
    name="gui",
    help="Launch the Sophia web interface.",
)


@app.default
def launch(
    *,
    host: Annotated[str, cyclopts.Parameter(help="Bind address.")] = "127.0.0.1",
    port: Annotated[int, cyclopts.Parameter(help="Port number.")] = 8080,
    reload: Annotated[bool, cyclopts.Parameter(help="Auto-reload on code changes.")] = False,
    native: Annotated[bool, cyclopts.Parameter(help="Open in a native window.")] = False,
) -> None:
    """Start the NiceGUI web server."""
    from sophia.config import Settings

    if host == "0.0.0.0":  # noqa: S104
        console = get_console()
        console.print(
            "[bold yellow]⚠ Binding to 0.0.0.0[/] — the GUI will be accessible "
            "from your network. Use --host 127.0.0.1 (default) to restrict to localhost.",
        )

    settings = Settings(gui_host=host, gui_port=port, gui_reload=reload)

    from nicegui import ui

    from sophia.gui.app import configure

    configure(settings)
    ui.run(  # type: ignore[reportUnknownMemberType]
        host=host,
        port=port,
        title="Sophia",
        reload=reload,
        show=native,
        storage_secret="sophia-gui-storage",
    )
