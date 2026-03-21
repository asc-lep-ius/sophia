"""Chronos — Deadline discovery and effort estimation commands."""

from __future__ import annotations

from typing import Annotated

import cyclopts

app = cyclopts.App(
    name="deadlines",
    help=(
        "Chronos — Deadline discovery and effort estimation.\n"
        "\n"
        "Workflow:\n"
        " 1. sync                          — fetch deadlines from all enrolled courses\n"
        " 2. list [--horizon N] [--course] — show upcoming deadlines\n"
        " 3. estimate DEADLINE_ID          — predict your effort with scaffold support\n"
    ),
)


@app.command(name="sync")
async def deadlines_sync() -> None:
    """Force refresh of deadline cache from TUWEL/TISS."""
    from rich.console import Console
    from rich.status import Status

    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app
    from sophia.services.chronos import sync_deadlines

    console = Console()

    try:
        async with create_app() as container:
            with Status("Syncing deadlines from all courses…", console=console):
                deadlines = await sync_deadlines(container)
            console.print(f"[green]✓ Synced {len(deadlines)} deadline(s)[/green]")
    except AuthError:
        console.print("[red]Not logged in. Run 'sophia auth login' first.[/red]")
        raise SystemExit(1) from None


@app.command(name="list")
async def deadlines_list(
    *,
    horizon: Annotated[
        int, cyclopts.Parameter(help="Number of days to look ahead.", name="--horizon")
    ] = 14,
    course: Annotated[
        str | None,
        cyclopts.Parameter(help="Filter by course name substring.", name="--course"),
    ] = None,
) -> None:
    """Show upcoming deadlines in a table."""
    from rich.console import Console
    from rich.table import Table

    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app
    from sophia.services.chronos import get_deadlines

    console = Console()

    try:
        async with create_app() as container:
            deadlines = await get_deadlines(container.db, horizon_days=horizon)

            if course:
                needle = course.lower()
                deadlines = [d for d in deadlines if needle in d.course_name.lower()]

            if not deadlines:
                console.print("[yellow]No upcoming deadlines found.[/yellow]")
                return

            table = Table(title=f"Upcoming Deadlines (next {horizon} days)")
            table.add_column("Due", style="cyan", no_wrap=True)
            table.add_column("Name", style="bold")
            table.add_column("Course")
            table.add_column("Type")
            table.add_column("Status")

            for d in deadlines:
                due_str = d.due_at.strftime("%Y-%m-%d %H:%M")
                type_style = {
                    "exam": "[red]exam[/red]",
                    "exam_registration": "[red]reg[/red]",
                    "assignment": "[blue]assign[/blue]",
                    "quiz": "[magenta]quiz[/magenta]",
                    "checkmark": "[green]check[/green]",
                }.get(d.deadline_type.value, d.deadline_type.value)

                table.add_row(
                    due_str,
                    d.name,
                    d.course_name,
                    type_style,
                    d.submission_status or "",
                )

            console.print(table)
    except AuthError:
        console.print("[red]Not logged in. Run 'sophia auth login' first.[/red]")
        raise SystemExit(1) from None


@app.command(name="estimate")
async def deadlines_estimate(
    deadline_id: Annotated[str, cyclopts.Parameter(help="Deadline ID (e.g. 'assign:123').")],
) -> None:
    """Interactively estimate effort for a deadline with scaffold support."""
    import contextlib

    from rich.console import Console
    from rich.panel import Panel

    from sophia.domain.errors import AuthError
    from sophia.domain.models import DeadlineType, EstimationScaffold
    from sophia.infra.di import create_app
    from sophia.services.chronos import (
        format_reference_class_hint,
        get_scaffold_level,
        record_estimate,
    )

    console = Console()

    try:
        async with create_app() as container:
            db = container.db

            # Look up the deadline
            cursor = await db.execute(
                "SELECT name, course_id, deadline_type, course_name "
                "FROM deadline_cache WHERE id = ?",
                (deadline_id,),
            )
            row = await cursor.fetchone()
            if not row:
                console.print(
                    f"[red]Deadline '{deadline_id}' not found. "
                    "Run 'sophia deadlines sync' first.[/red]"
                )
                raise SystemExit(1)

            name, course_id, dtype_str, course_name = row
            deadline_type = DeadlineType(dtype_str)

            console.print(Panel(f"[bold]{name}[/bold]\n{course_name}", title="Estimating Effort"))

            scaffold = await get_scaffold_level(db, deadline_type, course_id=course_id)

            # Show reference class hint if available
            hint = await format_reference_class_hint(db, deadline_type, course_id=course_id)
            if hint:
                console.print(f"[dim]📊 {hint}[/dim]\n")

            breakdown: dict[str, float] | None = None
            intention: str | None = None

            if scaffold == EstimationScaffold.FULL:
                console.print("[dim]Full scaffold — breaking down your estimate:[/dim]")
                console.print("Think about each phase: reading, coding, writing, reviewing…")
                breakdown_input = input("Breakdown (e.g. 'reading:2,coding:3,writing:1'): ").strip()
                if breakdown_input:
                    parsed: dict[str, float] = {}
                    for part in breakdown_input.split(","):
                        if ":" in part:
                            k, v = part.split(":", 1)
                            with contextlib.suppress(ValueError):
                                parsed[k.strip()] = float(v.strip())
                    if parsed:
                        breakdown = parsed

            hours_input = input("Total estimated hours: ").strip()
            try:
                predicted_hours = float(hours_input)
            except ValueError:
                console.print("[red]Invalid number.[/red]")
                raise SystemExit(1) from None

            if predicted_hours <= 0:
                console.print("[red]Hours must be positive.[/red]")
                raise SystemExit(1)

            if scaffold == EstimationScaffold.FULL:
                intention = input("When and where do you plan to work on this? ").strip() or None

            est = await record_estimate(
                container,
                deadline_id=deadline_id,
                course_id=course_id,
                predicted_hours=predicted_hours,
                breakdown=breakdown,
                intention=intention,
            )

            console.print(
                f"\n[green]✓ Recorded {est.predicted_hours:.1f}h estimate "
                f"(scaffold: {est.scaffold_level})[/green]"
            )
    except AuthError:
        console.print("[red]Not logged in. Run 'sophia auth login' first.[/red]")
        raise SystemExit(1) from None
