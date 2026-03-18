"""Scheduled job management commands."""

from __future__ import annotations

import cyclopts

app = cyclopts.App(name="jobs", help="Manage scheduled jobs.")


@app.command(name="list")
async def jobs_list() -> None:
    """Show all scheduled jobs."""
    from rich.console import Console
    from rich.table import Table

    from sophia.config import Settings
    from sophia.infra.persistence import connect_db, run_migrations
    from sophia.infra.scheduler import create_scheduler

    settings = Settings()
    db = await connect_db(settings.db_path)
    try:
        await run_migrations(db)
        scheduler = create_scheduler(db)
        jobs = await scheduler.list_jobs()
    finally:
        await db.close()

    console = Console()
    if not jobs:
        console.print("[yellow]No scheduled jobs.[/yellow]")
        return

    table = Table(title="Scheduled Jobs")
    table.add_column("Job ID", style="dim")
    table.add_column("Command", style="cyan")
    table.add_column("Scheduled For", style="green")
    table.add_column("Status", style="magenta")
    table.add_column("Description")

    for job in jobs:
        status_style = {
            "pending": "yellow",
            "running": "cyan",
            "completed": "green",
            "failed": "red",
            "cancelled": "dim",
        }.get(job.status.value, "white")
        table.add_row(
            job.job_id,
            job.command,
            job.scheduled_for,
            f"[{status_style}]{job.status.value}[/{status_style}]",
            job.description,
        )

    console.print(table)


@app.command
async def cancel(job_id: str) -> None:
    """Cancel a scheduled job."""
    from rich.console import Console

    from sophia.config import Settings
    from sophia.infra.persistence import connect_db, run_migrations
    from sophia.infra.scheduler import SchedulerError, create_scheduler

    console = Console()
    settings = Settings()
    db = await connect_db(settings.db_path)
    try:
        await run_migrations(db)
        scheduler = create_scheduler(db)

        job = await scheduler.get_job(job_id)
        if job is None:
            console.print(f"[red]Job not found: {job_id}[/red]")
            raise SystemExit(1)

        try:
            await scheduler.cancel(job_id)
        except SchedulerError as exc:
            console.print(f"[red]Failed to cancel: {exc}[/red]")
            raise SystemExit(1) from None

        console.print(f"[green]Job {job_id} cancelled.[/green]")
    finally:
        await db.close()
