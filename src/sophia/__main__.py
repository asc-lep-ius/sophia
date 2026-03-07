"""CLI entry point for Sophia."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import cyclopts
import structlog

import sophia
from sophia.infra.logging import setup_logging

if TYPE_CHECKING:
    from sophia.adapters.auth import TissSessionCredentials
    from sophia.config import Settings

app = cyclopts.App(
    name="sophia",
    help="Σοφία — A student toolkit for TU Wien's TUWEL.",
    version=sophia.__version__,
)

books_app = cyclopts.App(name="books", help="Book discovery and download commands.")
app.command(books_app)

auth_app = cyclopts.App(name="auth", help="Session authentication commands.")
app.command(auth_app)

register_app = cyclopts.App(name="register", help="Kairos — TISS course & group registration.")
app.command(register_app)

log = structlog.get_logger()


def _current_semester() -> str:
    """Infer current TISS semester from the date (e.g., '2026S' or '2025W')."""
    today = date.today()
    if today.month >= 10 or today.month <= 1:
        year = today.year if today.month >= 10 else today.year - 1
        return f"{year}W"
    return f"{today.year}S"


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


# --- Kairos: TISS registration commands ---


@register_app.command
async def tiss_login() -> None:
    """Log in to TISS via TU Wien SSO."""
    import getpass
    import os

    from sophia.adapters.auth import login_tiss, save_tiss_session, tiss_session_path
    from sophia.config import Settings

    settings = Settings()
    username = os.environ.get("SOPHIA_TUWEL_USERNAME") or input("TU Wien username: ")
    password = getpass.getpass("TU Wien password: ")
    creds = await login_tiss(settings.tiss_host, username, password)
    path = tiss_session_path(settings.config_dir)
    save_tiss_session(creds, path)
    log.info("tiss_login_complete", msg="TISS session saved.")


def _require_tiss_session() -> tuple[Settings, TissSessionCredentials | None]:
    """Load TISS session or return (settings, None) if not logged in."""
    from sophia.adapters.auth import load_tiss_session, tiss_session_path
    from sophia.config import Settings

    settings = Settings()
    creds = load_tiss_session(tiss_session_path(settings.config_dir))
    return settings, creds


@register_app.command(name="status")
async def reg_status(course_number: str, *, semester: str = "") -> None:
    """Check registration status for a course on TISS."""
    from rich.console import Console

    from sophia.adapters.tiss_registration import TissRegistrationAdapter
    from sophia.infra.http import http_session

    console = Console()
    settings, tiss_creds = _require_tiss_session()
    if tiss_creds is None:
        console.print("[red]Not logged in to TISS — run:[/red] sophia register tiss-login")
        raise SystemExit(1)

    if not semester:
        semester = _current_semester()

    async with http_session() as http:
        adapter = TissRegistrationAdapter(
            http=http,
            credentials=tiss_creds,
            host=settings.tiss_host,
        )
        target = await adapter.get_registration_status(course_number, semester)

    console.print(f"\n[bold]{target.title or course_number}[/bold]")
    console.print(f"Status: [cyan]{target.status.value}[/cyan]")
    if target.registration_start:
        console.print(f"Opens:  {target.registration_start}")
    if target.registration_end:
        console.print(f"Closes: {target.registration_end}")


@register_app.command
async def groups(course_number: str, *, semester: str = "") -> None:
    """Show available groups for a course with day/time schedule."""
    from rich.console import Console
    from rich.table import Table

    from sophia.adapters.tiss_registration import TissRegistrationAdapter
    from sophia.infra.http import http_session

    console = Console()
    settings, tiss_creds = _require_tiss_session()
    if tiss_creds is None:
        console.print("[red]Not logged in to TISS — run:[/red] sophia register tiss-login")
        raise SystemExit(1)

    if not semester:
        semester = _current_semester()

    async with http_session() as http:
        adapter = TissRegistrationAdapter(
            http=http,
            credentials=tiss_creds,
            host=settings.tiss_host,
        )
        grps = await adapter.get_groups(course_number, semester)

    if not grps:
        console.print("[yellow]No groups found.[/yellow]")
        return

    table = Table(title=f"Groups for {course_number} ({semester})")
    table.add_column("#", style="dim", width=3)
    table.add_column("Name", style="cyan")
    table.add_column("Day", style="green")
    table.add_column("Time", style="green")
    table.add_column("Location", style="blue")
    table.add_column("Enrolled", justify="right")
    table.add_column("Capacity", justify="right")
    table.add_column("Status", style="magenta")

    for i, g in enumerate(grps, 1):
        time_str = f"{g.time_start}\u2013{g.time_end}" if g.time_start else "\u2014"
        enrolled_style = "red" if g.enrolled >= g.capacity and g.capacity > 0 else "white"
        table.add_row(
            str(i),
            g.name,
            g.day or "\u2014",
            time_str,
            g.location or "\u2014",
            f"[{enrolled_style}]{g.enrolled}[/{enrolled_style}]",
            str(g.capacity) if g.capacity else "\u2014",
            g.status.value,
        )

    console.print(table)
    console.print(
        f"\n[dim]Use [cyan]sophia register go {course_number}"
        ' --preferences "1,3,2"[/cyan] to register with group preferences.[/dim]',
    )


@register_app.command
async def favorites(*, semester: str = "") -> None:
    """List your TISS favorites with registration status."""
    from rich.console import Console
    from rich.table import Table

    from sophia.adapters.tiss_registration import TissRegistrationAdapter
    from sophia.infra.http import http_session

    console = Console()
    settings, tiss_creds = _require_tiss_session()
    if tiss_creds is None:
        console.print("[red]Not logged in to TISS — run:[/red] sophia register tiss-login")
        raise SystemExit(1)

    if not semester:
        semester = _current_semester()

    async with http_session() as http:
        adapter = TissRegistrationAdapter(
            http=http,
            credentials=tiss_creds,
            host=settings.tiss_host,
        )
        favs = await adapter.get_favorites(semester)

    if not favs:
        console.print("[yellow]No favorites found.[/yellow]")
        return

    table = Table(title=f"TISS Favorites ({semester})")
    table.add_column("Course Number", style="dim")
    table.add_column("Title", style="cyan bold")
    table.add_column("Type", style="dim")
    table.add_column("Hours", justify="right")
    table.add_column("ECTS", justify="right")
    table.add_column("LVA", justify="center")
    table.add_column("Group", justify="center")
    table.add_column("Exam", justify="center")

    for fav in favs:
        table.add_row(
            fav.course_number,
            fav.title,
            fav.course_type,
            f"{fav.hours:g}",
            f"{fav.ects:g}",
            "[green]✓[/green]" if fav.lva_registered else "[dim]✗[/dim]",
            "[green]✓[/green]" if fav.group_registered else "[dim]✗[/dim]",
            "[green]✓[/green]" if fav.exam_registered else "[dim]✗[/dim]",
        )

    console.print(table)
    console.print(
        "\n[dim]Use [cyan]sophia register status <course-number>[/cyan] for details.[/dim]",
    )


@register_app.command
async def go(
    course_number: str,
    *,
    semester: str = "",
    preferences: str = "",
    watch: bool = False,
) -> None:
    """Register for a course or group. Use --watch to wait for the window.

    Examples:
        sophia register go 186.813                     # LVA registration
        sophia register go 186.813 --preferences 1,3   # groups by index
        sophia register go 186.813 --watch              # wait for window
    """
    from rich.console import Console

    from sophia.adapters.tiss_registration import TissRegistrationAdapter
    from sophia.infra.http import http_session
    from sophia.services.registration import register_with_preferences, watch_and_register

    console = Console()
    settings, tiss_creds = _require_tiss_session()
    if tiss_creds is None:
        console.print("[red]Not logged in to TISS — run:[/red] sophia register tiss-login")
        raise SystemExit(1)

    if not semester:
        semester = _current_semester()

    async with http_session() as http:
        adapter = TissRegistrationAdapter(
            http=http,
            credentials=tiss_creds,
            host=settings.tiss_host,
        )

        pref_ids: list[str] = []
        if preferences:
            grps = await adapter.get_groups(course_number, semester)
            indices = [int(x.strip()) - 1 for x in preferences.split(",") if x.strip().isdigit()]
            for idx in indices:
                if 0 <= idx < len(grps):
                    pref_ids.append(grps[idx].group_id)
                else:
                    console.print(
                        f"[yellow]Warning: group index {idx + 1} out of range, skipping[/yellow]",
                    )

        if watch:
            console.print(f"[cyan]Watching registration for {course_number}...[/cyan]")
            console.print("[dim]Press Ctrl+C to cancel.[/dim]")
            try:
                result = await watch_and_register(
                    adapter,
                    course_number,
                    semester,
                    pref_ids,
                )
            except KeyboardInterrupt:
                console.print("\n[yellow]Watch cancelled.[/yellow]")
                return
        else:
            result = await register_with_preferences(
                adapter,
                course_number,
                semester,
                pref_ids,
            )

    if result.success:
        console.print(f"\n[bold green]{result.message}[/bold green]")
        if result.group_name:
            console.print(f"   Group: {result.group_name}")
    else:
        console.print(f"\n[bold red]{result.message}[/bold red]")
        raise SystemExit(1)


def main() -> None:
    """Entry point called by the `sophia` console script."""
    setup_logging(debug=True)
    app()


if __name__ == "__main__":
    main()
