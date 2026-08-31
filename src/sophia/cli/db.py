"""Database management commands."""

from __future__ import annotations

import cyclopts

app = cyclopts.App(name="db", help="Database management commands.")


@app.command
async def status() -> None:
    """Show migration status — the revision applied versus the newest available."""
    from rich.console import Console

    from sophia.config import Settings
    from sophia.infra.alembic_runner import current_revision, head_revision
    from sophia.infra.engine import create_engine

    settings = Settings()
    console = Console()
    engine = create_engine(settings.database_url)
    try:
        applied = await current_revision(engine)
        head = head_revision(settings.database_url)

        console.print(f"[bold]Database:[/bold] {_redacted(settings.database_url)}")
        console.print(f"[bold]Applied revision:[/bold] {applied or '(none)'}")
        console.print(f"[bold]Head revision:[/bold] {head or '(none)'}")

        if applied != head:
            console.print("\n[yellow]Database is behind — run: sophia db upgrade[/yellow]")
    finally:
        await engine.dispose()


@app.command
async def upgrade(revision: str = "head") -> None:
    """Apply migrations up to a revision (default: head)."""
    from rich.console import Console

    from sophia.config import Settings
    from sophia.infra.alembic_runner import upgrade_async

    settings = Settings()
    await upgrade_async(settings.database_url, revision)
    Console().print(f"[green]Database upgraded to {revision}.[/green]")


def _redacted(database_url: str) -> str:
    """Hide the password before printing a connection string."""
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(database_url)
    if parsed.password is None:
        return database_url
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"{parsed.username}:***@{host}{port}" if parsed.username else f"{host}{port}"
    return urlunparse(parsed._replace(netloc=netloc))
