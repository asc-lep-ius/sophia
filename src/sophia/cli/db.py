"""Database management commands."""

from __future__ import annotations

import cyclopts

app = cyclopts.App(name="db", help="Database management commands.")


@app.command
async def status() -> None:
    """Show migration status — current version, applied, and pending."""
    from rich.console import Console

    from sophia.config import Settings
    from sophia.infra.persistence import connect_db, get_migration_status, run_migrations

    settings = Settings()
    console = Console()
    db = await connect_db(settings.db_path)
    try:
        await run_migrations(db)
        info = await get_migration_status(db)

        console.print(f"[bold]Database:[/bold] {settings.db_path}")
        console.print(f"[bold]Current version:[/bold] {info['current_version']}")
        console.print(f"[bold]Applied:[/bold] {len(info['applied'])}")
        console.print(f"[bold]Pending:[/bold] {len(info['pending'])}")

        if info["pending"]:
            console.print("\n[yellow]Pending migrations:[/yellow]")
            for m in info["pending"]:
                console.print(f"  {m['version']:03d} — {m['filename']}")
    finally:
        await db.close()
