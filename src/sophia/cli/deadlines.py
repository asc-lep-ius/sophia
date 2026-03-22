"""Chronos — Deadline discovery, effort estimation, and time tracking commands."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import cyclopts

if TYPE_CHECKING:
    from sophia.domain.models import Deadline

app = cyclopts.App(
    name="deadlines",
    help=(
        "Chronos — Deadline discovery, effort estimation, and time tracking.\n"
        "\n"
        "Workflow:\n"
        " 1. sync                          — fetch deadlines from all enrolled courses\n"
        " 2. list [--horizon N] [--course] — show upcoming deadlines\n"
        " 3. estimate DEADLINE_ID          — predict your effort with scaffold support\n"
        " 4. track DEADLINE_ID --hours N   — log manual time entry\n"
        " 5. timer start/stop DEADLINE_ID  — timer-based time tracking\n"
        " 6. done DEADLINE_ID              — mark complete → reflection prompt\n"
        " 7. stress [--horizon N]          — workload forecast for upcoming days\n"
        " 8. next                           — show highest-priority deadline\n"
    ),
)

timer_app = cyclopts.App(name="timer", help="Timer-based time tracking.")
app.command(timer_app)


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

            from sophia.services.athena_chronos import compress_all_courses

            compressed = await compress_all_courses(container.db)
            if compressed:
                total = sum(compressed.values())
                console.print(f"[dim]Compressed {total} review(s) for upcoming exams.[/dim]")
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
    sort: Annotated[
        str | None,
        cyclopts.Parameter(
            help="Sort by: due (default), urgency, weight, effort.",
            name="--sort",
        ),
    ] = None,
) -> None:
    """Show upcoming deadlines in a table."""
    from rich.console import Console
    from rich.table import Table

    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app
    from sophia.services.chronos import compute_priority_score, get_deadlines, get_tracked_time

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

            # Pre-fetch estimates and tracked time for sort + display
            deadline_data: list[tuple[Deadline, float | None, float]] = []
            for d in deadlines:
                est_cursor = await container.db.execute(
                    "SELECT predicted_hours FROM effort_estimates "
                    "WHERE deadline_id = ? ORDER BY estimated_at DESC LIMIT 1",
                    (d.id,),
                )
                est_row = await est_cursor.fetchone()
                est_hours = float(est_row[0]) if est_row else None

                tracked = await get_tracked_time(container.db, d.id)
                deadline_data.append((d, est_hours, tracked))

            # Apply sort
            if sort == "urgency":
                deadline_data.sort(
                    key=lambda t: compute_priority_score(t[0], t[1], t[2])["score"],
                    reverse=True,
                )
            elif sort == "weight":
                deadline_data.sort(
                    key=lambda t: t[0].grade_weight or 0,
                    reverse=True,
                )
            elif sort == "effort":
                deadline_data.sort(
                    key=lambda t: compute_priority_score(t[0], t[1], t[2])["effort_gap"],
                    reverse=True,
                )
            # default (due): already sorted by due_at ASC from the query

            table = Table(title=f"Upcoming Deadlines (next {horizon} days)")
            table.add_column("Due", style="cyan", no_wrap=True)
            table.add_column("Name", style="bold")
            table.add_column("Course")
            table.add_column("Type")
            table.add_column("Estimate", justify="right")
            table.add_column("Tracked", justify="right")
            if sort == "urgency":
                table.add_column("Priority", justify="right")
            table.add_column("Status")

            for d, est_hours, tracked in deadline_data:
                due_str = d.due_at.strftime("%Y-%m-%d %H:%M")
                type_style = {
                    "exam": "[red]exam[/red]",
                    "exam_registration": "[red]reg[/red]",
                    "assignment": "[blue]assign[/blue]",
                    "quiz": "[magenta]quiz[/magenta]",
                    "checkmark": "[green]check[/green]",
                }.get(d.deadline_type.value, d.deadline_type.value)

                est_str = f"{est_hours:.1f}h" if est_hours is not None else ""
                tracked_str = f"{tracked:.1f}h" if tracked > 0 else ""

                row: list[str] = [
                    due_str,
                    d.name,
                    d.course_name,
                    type_style,
                    est_str,
                    tracked_str,
                ]
                if sort == "urgency":
                    ps = compute_priority_score(d, est_hours, tracked)
                    row.append(f"{ps['score']:.2f}")
                row.append(d.submission_status or "")

                table.add_row(*row)

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


@app.command(name="track")
async def deadlines_track(
    deadline_id: Annotated[str, cyclopts.Parameter(help="Deadline ID (e.g. 'assign:123').")],
    *,
    hours: Annotated[float, cyclopts.Parameter(help="Hours to log.", name="--hours")],
    note: Annotated[str | None, cyclopts.Parameter(help="Optional note.", name="--note")] = None,
) -> None:
    """Log a manual time entry for a deadline."""
    from rich.console import Console

    from sophia.infra.di import create_app
    from sophia.services.chronos import record_time

    console = Console()

    async with create_app() as container:
        await record_time(container.db, deadline_id, hours, note=note)
        console.print(
            f"[green]📝 Logged {hours:.1f}h.[/green] "
            "Quick and easy, but recall estimates tend to be ~30% low."
        )


@timer_app.command(name="start")
async def timer_start(
    deadline_id: Annotated[str, cyclopts.Parameter(help="Deadline ID (e.g. 'assign:123').")],
) -> None:
    """Start a timer for a deadline."""
    from rich.console import Console

    from sophia.domain.errors import ChronosError
    from sophia.infra.di import create_app
    from sophia.services.chronos import start_timer

    console = Console()

    async with create_app() as container:
        try:
            await start_timer(container.db, deadline_id)
            console.print(
                "[green]⏱ Timer started.[/green] More accurate, but remember to stop it when done."
            )
        except ChronosError as exc:
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(1) from None


@timer_app.command(name="stop")
async def timer_stop(
    deadline_id: Annotated[str, cyclopts.Parameter(help="Deadline ID (e.g. 'assign:123').")],
) -> None:
    """Stop a running timer and record the elapsed time."""
    from rich.console import Console

    from sophia.domain.errors import ChronosError
    from sophia.infra.di import create_app
    from sophia.services.chronos import stop_timer

    console = Console()

    async with create_app() as container:
        try:
            hours = await stop_timer(container.db, deadline_id)
            console.print(f"[green]⏱ Timer stopped — {hours:.2f}h recorded.[/green]")
        except ChronosError as exc:
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(1) from None


@app.command(name="done")
async def deadlines_done(
    deadline_id: Annotated[str, cyclopts.Parameter(help="Deadline ID (e.g. 'assign:123').")],
) -> None:
    """Mark a deadline complete — shows estimation feedback and prompts for reflection."""
    from rich.console import Console
    from rich.panel import Panel

    from sophia.infra.di import create_app
    from sophia.services.chronos import complete_deadline, record_reflection

    console = Console()

    async with create_app() as container:
        predicted, actual, feedback = await complete_deadline(container, deadline_id)
        console.print(Panel(feedback, title="Estimation Feedback"))

        reflection_text = input("Quick reflection (or Enter to skip): ").strip()
        if reflection_text:
            await record_reflection(
                container.db,
                deadline_id,
                predicted_hours=predicted,
                actual_hours=actual,
                reflection_text=reflection_text,
            )
            console.print("[green]✓ Reflection saved.[/green]")

        console.print("[dim]That one's past. Here's what's next.[/dim]")


@app.command(name="reflect")
async def deadlines_reflect(
    deadline_id: Annotated[str, cyclopts.Parameter(help="Deadline ID (e.g. 'assign:123').")],
) -> None:
    """Record a post-deadline reflection for a completed deadline."""
    from rich.console import Console

    from sophia.infra.di import create_app
    from sophia.services.chronos import get_tracked_time, record_reflection

    console = Console()

    async with create_app() as container:
        db = container.db

        # Get predicted hours
        cursor = await db.execute(
            "SELECT predicted_hours FROM effort_estimates "
            "WHERE deadline_id = ? ORDER BY estimated_at DESC LIMIT 1",
            (deadline_id,),
        )
        est_row = await cursor.fetchone()
        predicted = float(est_row[0]) if est_row else None

        actual = await get_tracked_time(db, deadline_id)

        if predicted is not None:
            console.print(f"[dim]Estimated: {predicted:.1f}h | Tracked: {actual:.1f}h[/dim]")
        else:
            console.print(f"[dim]Tracked: {actual:.1f}h (no estimate)[/dim]")

        reflection_text = input("What did you learn about your working process? ").strip()
        if not reflection_text:
            console.print("[yellow]No reflection entered.[/yellow]")
            return

        await record_reflection(
            db,
            deadline_id,
            predicted_hours=predicted,
            actual_hours=actual,
            reflection_text=reflection_text,
        )
        console.print("[green]✓ Reflection saved.[/green]")


@app.command(name="stress")
async def deadlines_stress(
    *,
    horizon: Annotated[int, cyclopts.Parameter(help="Days to look ahead.", name="--horizon")] = 7,
) -> None:
    """Show workload forecast — another lens on your upcoming deadlines."""
    from rich.console import Console
    from rich.table import Table

    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app
    from sophia.services.chronos import get_workload_forecast

    console = Console()

    try:
        async with create_app() as container:
            forecast = await get_workload_forecast(container.db, horizon_days=horizon)

            count = forecast["deadline_count"]
            est = forecast["total_estimated_hours"]
            tracked = forecast["total_tracked_hours"]
            remaining = forecast["remaining_hours"]

            console.print(
                f"\n[bold]Workload snapshot[/bold] (next {horizon} days): "
                f"{count} deadline(s), ~{est:.1f}h estimated, "
                f"~{tracked:.1f}h tracked, ~{remaining:.1f}h remaining\n"
            )

            per_day: dict[str, list[tuple[str, float]]] = forecast["per_day"]  # type: ignore[assignment]
            if not per_day:
                console.print("[dim]Nothing on the horizon — enjoy the calm.[/dim]")
                return

            HEAVY_THRESHOLD = 4.0
            MEDIUM_THRESHOLD = 2.0

            table = Table(title="Day-by-day view")
            table.add_column("Date", style="cyan")
            table.add_column("Deadlines", justify="right")
            table.add_column("Remaining", justify="right")
            table.add_column("Load")

            for date_str, items in sorted(per_day.items()):
                day_remaining = sum(r for _, r in items)
                if day_remaining > HEAVY_THRESHOLD:
                    load = "[red]heavy[/red]"
                elif day_remaining > MEDIUM_THRESHOLD:
                    load = "[yellow]medium[/yellow]"
                else:
                    load = "[green]light[/green]"
                table.add_row(
                    date_str,
                    str(len(items)),
                    f"{day_remaining:.1f}h",
                    load,
                )

            console.print(table)
            console.print(
                "\n[dim]This is one lens on your workload — "
                "not the definitive answer on what to do first.[/dim]"
            )
    except AuthError:
        console.print("[red]Not logged in. Run 'sophia auth login' first.[/red]")
        raise SystemExit(1) from None


@app.command(name="next")
async def deadlines_next() -> None:
    """Show the highest-priority deadline with context."""
    from rich.console import Console
    from rich.panel import Panel

    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app
    from sophia.services.chronos import compute_priority_score, get_deadlines, get_tracked_time

    console = Console()

    try:
        async with create_app() as container:
            deadlines = await get_deadlines(container.db, horizon_days=14)

            if not deadlines:
                console.print("[yellow]No upcoming deadlines.[/yellow]")
                return

            scored: list[tuple[Deadline, dict[str, float], float | None, float]] = []
            for d in deadlines:
                est_cursor = await container.db.execute(
                    "SELECT predicted_hours FROM effort_estimates "
                    "WHERE deadline_id = ? ORDER BY estimated_at DESC LIMIT 1",
                    (d.id,),
                )
                est_row = await est_cursor.fetchone()
                est_hours = float(est_row[0]) if est_row else None

                tracked = await get_tracked_time(container.db, d.id)
                ps = compute_priority_score(d, est_hours, tracked)
                scored.append((d, ps, est_hours, tracked))

            scored.sort(key=lambda t: t[1]["score"], reverse=True)
            top, ps, est_hours, tracked = scored[0]

            est_str = f"{est_hours:.1f}h" if est_hours is not None else "no estimate"
            lines = [
                f"[bold]{top.name}[/bold]",
                f"Course: {top.course_name}",
                f"Due: {top.due_at.strftime('%Y-%m-%d %H:%M')}",
                f"Type: {top.deadline_type.value}",
                f"Estimate: {est_str}  |  Tracked: {tracked:.1f}h",
                "",
                "[dim]Priority components:[/dim]",
                f"  urgency: {ps['urgency']:.3f}  (closer = higher)",
                f"  importance: {ps['importance']:.2f}  (grade weight)",
                f"  effort gap: {ps['effort_gap']:.1f}h  (remaining work)",
                f"  → score: {ps['score']:.3f}",
            ]

            console.print(Panel("\n".join(lines), title="Next Up"))
    except AuthError:
        console.print("[red]Not logged in. Run 'sophia auth login' first.[/red]")
        raise SystemExit(1) from None


@app.command(name="calibration")
async def deadlines_calibration() -> None:
    """Show per-domain estimation accuracy dashboard."""
    from rich.console import Console
    from rich.table import Table

    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app
    from sophia.services.chronos import get_calibration_metrics

    console = Console()
    try:
        async with create_app() as container:
            metrics = await get_calibration_metrics(container.db)

            if not metrics:
                console.print("[dim]No calibration data yet — complete ≥3 estimates first.[/dim]")
                return

            trend_icons = {"improving": "↑", "stable": "→", "declining": "↓"}
            table = Table(title="Estimation Calibration")
            table.add_column("Domain")
            table.add_column("Samples", justify="right")
            table.add_column("Bias", justify="right")
            table.add_column("MAE", justify="right")
            table.add_column("Trend", justify="center")

            for m in metrics:
                sign = "+" if m.mean_error >= 0 else ""
                table.add_row(
                    m.domain.removeprefix("effort:"),
                    str(m.sample_count),
                    f"{sign}{m.mean_error:.1f}h",
                    f"±{m.mean_absolute_error:.1f}h",
                    trend_icons.get(m.trend, "?"),
                )
            console.print(table)
    except AuthError:
        console.print("[red]Not logged in. Run 'sophia auth login' first.[/red]")
        raise SystemExit(1) from None


@app.command(name="export-ics")
async def deadlines_export_ics(
    *,
    horizon: int = 30,
    output: str | None = None,
) -> None:
    """Export deadlines as ICS calendar file."""
    from pathlib import Path

    from rich.console import Console

    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app
    from sophia.services.chronos import export_deadlines_ics

    console = Console()
    try:
        async with create_app() as container:
            ics_str = await export_deadlines_ics(container.db, horizon_days=horizon)
            out_path = Path(output or "sophia_deadlines.ics")
            out_path.write_text(ics_str)
            console.print(f"[green]Exported to {out_path}[/green]")
    except AuthError:
        console.print("[red]Not logged in. Run 'sophia auth login' first.[/red]")
        raise SystemExit(1) from None
