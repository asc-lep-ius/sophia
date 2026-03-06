"""CLI entry point for Sophia."""

from __future__ import annotations

import cyclopts
import structlog

import sophia
from sophia.infra.logging import setup_logging

app = cyclopts.App(
    name="sophia",
    help="Σοφία — A student toolkit for TU Wien's TUWEL.",
    version=sophia.__version__,
)

books_app = cyclopts.App(name="books", help="Book discovery and download commands.")
app.command(books_app)

auth_app = cyclopts.App(name="auth", help="Session authentication commands.")
app.command(auth_app)

log = structlog.get_logger()


@books_app.command
async def discover() -> None:
    """Discover book references from enrolled TUWEL courses."""
    from rich.console import Console
    from rich.table import Table

    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app
    from sophia.services.pipeline import discover_books
    from sophia.services.reference_extractor import RegexReferenceExtractor

    console = Console()

    try:
        async with create_app() as container:
            extractor = RegexReferenceExtractor()
            refs = await discover_books(
                courses=container.moodle,
                resources=container.moodle,
                extractor=extractor,
                metadata=container.tiss,
            )
    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None

    if not refs:
        console.print("[yellow]No book references found in enrolled courses.[/yellow]")
        return

    table = Table(title="Discovered Book References")
    table.add_column("Title", style="cyan", no_wrap=False)
    table.add_column("Author(s)", style="green")
    table.add_column("ISBN", style="magenta")
    table.add_column("Source", style="blue")
    table.add_column("Course", style="yellow", no_wrap=False)

    for ref in refs:
        table.add_row(
            ref.title or "—",
            ", ".join(ref.authors) if ref.authors else "—",
            ref.isbn or "—",
            ref.source.value,
            ref.course_name or "—",
        )

    console.print(table)


@auth_app.command
async def login() -> None:
    """Log in to TUWEL via TU Wien SSO (username/password)."""
    import getpass
    import os

    from sophia.adapters.auth import login_with_credentials, save_session, session_path
    from sophia.config import Settings

    settings = Settings()

    username = os.environ.get("SOPHIA_TUWEL_USERNAME") or input("TU Wien username: ")
    password = getpass.getpass("TU Wien password: ")

    creds = await login_with_credentials(settings.tuwel_host, username, password)
    path = session_path(settings.config_dir)
    save_session(creds, path)
    log.info("login_complete", msg="Session saved. You can now use sophia commands.")


@auth_app.command
async def status() -> None:
    """Check if the current session is valid."""
    from sophia.adapters.auth import load_session, session_path
    from sophia.adapters.moodle import MoodleAdapter
    from sophia.config import Settings
    from sophia.domain.errors import AuthError
    from sophia.infra.http import http_session

    settings = Settings()
    creds = load_session(session_path(settings.config_dir))
    if creds is None:
        log.error("not_logged_in", msg="No session found. Run: sophia auth login")
        raise SystemExit(1)

    async with http_session() as http:
        adapter = MoodleAdapter(
            http=http,
            sesskey=creds.sesskey,
            moodle_session=creds.moodle_session,
            host=settings.tuwel_host,
            cookie_name=creds.cookie_name,
        )
        try:
            await adapter.check_session()
            log.info("session_valid", msg="Session is active.")
        except AuthError:
            log.error("session_expired", msg="Session expired. Run: sophia auth login")
            raise SystemExit(1) from None


@auth_app.command
def logout() -> None:
    """Clear stored session credentials."""
    from sophia.adapters.auth import clear_session, session_path
    from sophia.config import Settings

    settings = Settings()
    clear_session(session_path(settings.config_dir))
    log.info("logged_out", msg="Session cleared.")


def main() -> None:
    """Entry point called by the `sophia` console script."""
    setup_logging(debug=True)
    app()


if __name__ == "__main__":
    main()
