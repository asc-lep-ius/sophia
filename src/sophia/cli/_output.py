"""Shared CLI helpers used across sub-apps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sophia.adapters.auth import TissSessionCredentials
    from sophia.config import Settings


@dataclass
class OutputConfig:
    """Global output settings — set by main() before any command runs."""

    json_mode: bool = False
    quiet: bool = False
    no_color: bool = False
    debug: bool = False


# Singleton configured by __main__.main() at startup
output = OutputConfig()


def get_console() -> Any:
    """Create a Rich Console respecting global output settings."""
    from rich.console import Console

    return Console(no_color=output.no_color, quiet=output.quiet)


def print_json_or_table(data: list[dict[str, Any]], table: Any) -> None:
    """Print *data* as JSON when --json is active, otherwise print *table*."""
    console = get_console()
    if output.json_mode:
        import json

        console.print(json.dumps(data, indent=2, default=str))
    else:
        console.print(table)


def handle_cli_error(exc: Exception) -> None:
    """Print a user-friendly error message and exit with code 1."""
    import httpx

    from sophia.domain.errors import AuthError, TopicExtractionError

    console = get_console()

    if isinstance(exc, AuthError):
        console.print("[red]Not logged in[/red] — run: sophia auth login")
    elif isinstance(exc, httpx.ConnectError):
        console.print("[red]Connection failed[/red] — check your network and try again")
    elif isinstance(exc, httpx.TimeoutException):
        console.print(f"[red]Request timed out[/red] — {exc}")
    elif isinstance(exc, TopicExtractionError):
        console.print(f"[red]Topic extraction failed:[/red] {exc}")
    else:
        console.print(f"[red]Error:[/red] {exc}")

    if output.debug:
        console.print_exception()

    raise SystemExit(1)


def current_semester() -> str:
    """Infer current TISS semester from the date (e.g., '2026S' or '2025W')."""
    today = date.today()
    if today.month >= 10 or today.month <= 1:
        year = today.year if today.month >= 10 else today.year - 1
        return f"{year}W"
    return f"{today.year}S"


def require_tiss_session() -> tuple[Settings, TissSessionCredentials | None]:
    """Load TISS session or return (settings, None) if not logged in."""
    from sophia.adapters.auth import load_tiss_session, tiss_session_path
    from sophia.config import Settings

    settings = Settings()
    creds = load_tiss_session(tiss_session_path(settings.config_dir))
    return settings, creds
