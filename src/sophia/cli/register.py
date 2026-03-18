"""Kairos — TISS course & group registration commands."""

from __future__ import annotations

from typing import Annotated

import cyclopts

from sophia.cli._output import _current_semester, _require_tiss_session, get_console

app = cyclopts.App(
    name="register",
    help=(
        "Kairos — TISS course & group registration.\n"
        "\n"
        "Workflow:\n"
        " 1. favorites                          — list TISS favorites with course numbers\n"
        " 2. status  COURSE_NR                  — check registration window times\n"
        " 3. groups  COURSE_NR                  — show available groups with indices\n"
        " 4. go      COURSE_NR                  — register now (LVA)\n"
        " 5. go      COURSE_NR --preferences 1,3 — register for groups by preference\n"
        " 6. go      COURSE_NR --schedule       — schedule job at registration open time\n"
        " 7. go      COURSE_NR --watch          — poll until window opens, then register\n"
        "\n"
        "Course numbers are TISS numbers like 186.813 (find via favorites or TISS URL)."
    ),
)


@app.command(name="status")
async def reg_status(
    course_number: Annotated[str, cyclopts.Parameter(help="TISS course number, e.g. 186.813")],
    *,
    semester: Annotated[str, cyclopts.Parameter(help="Semester code (default: current)")] = "",
) -> None:
    """Check registration status and window times for a course on TISS."""
    from rich.console import Console

    from sophia.adapters.tiss_registration import TissRegistrationAdapter
    from sophia.infra.http import http_session

    console = Console()
    settings, tiss_creds = _require_tiss_session()
    if tiss_creds is None:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
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


@app.command
async def groups(
    course_number: Annotated[str, cyclopts.Parameter(help="TISS course number, e.g. 186.813")],
    *,
    semester: Annotated[str, cyclopts.Parameter(help="Semester code (default: current)")] = "",
) -> None:
    """Show available groups for a course with day/time schedule.

    Use the group indices (#) with 'sophia register go --preferences'."""
    from rich.console import Console
    from rich.table import Table

    from sophia.adapters.tiss_registration import TissRegistrationAdapter
    from sophia.infra.http import http_session

    console = Console()
    settings, tiss_creds = _require_tiss_session()
    if tiss_creds is None:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
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


@app.command
async def favorites(
    *,
    semester: Annotated[str, cyclopts.Parameter(help="Semester code (default: current)")] = "",
) -> None:
    """List your TISS favorites with registration status."""
    from rich.console import Console
    from rich.table import Table

    from sophia.adapters.tiss_registration import TissRegistrationAdapter
    from sophia.infra.http import http_session

    console = Console()
    settings, tiss_creds = _require_tiss_session()
    if tiss_creds is None:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
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


@app.command
async def go(
    course_number: Annotated[str, cyclopts.Parameter(help="TISS course number, e.g. 186.813")],
    *,
    semester: Annotated[
        str, cyclopts.Parameter(help="Semester code, e.g. 2026S (default: current)")
    ] = "",
    preferences: Annotated[
        str,
        cyclopts.Parameter(
            help="Comma-separated group indices from 'sophia register groups', e.g. 1,3,2"
        ),
    ] = "",
    watch: Annotated[
        bool,
        cyclopts.Parameter(help="Poll until the registration window opens, then register"),
    ] = False,
    schedule: Annotated[
        bool,
        cyclopts.Parameter(help="Schedule a system job to register at the exact opening time"),
    ] = False,
    dry_run: Annotated[
        bool,
        cyclopts.Parameter(name="--dry-run", help="Show registration plan without submitting"),
    ] = False,
) -> None:
    """Register for a course (LVA) or specific groups on TISS.

    Without --preferences, registers directly for the course (LVA registration).
    With --preferences, tries each group in order and stops at first success.

    Examples:
        sophia register go 186.813                     # LVA registration
        sophia register go 186.813 --preferences 1,3   # groups 1 then 3
        sophia register go 186.813 --watch              # wait for window
        sophia register go 186.813 --schedule           # schedule at open time

    Find course numbers:
        sophia register favorites                       # from your TISS favorites
        Or check the URL on TISS: courseNr=186813 → 186.813
    """
    from sophia.adapters.tiss_registration import TissRegistrationAdapter
    from sophia.infra.http import http_session
    from sophia.services.registration import register_with_preferences, watch_and_register

    console = get_console()
    settings, tiss_creds = _require_tiss_session()
    if tiss_creds is None:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1)

    if not semester:
        semester = _current_semester()

    if dry_run:
        console.print("\n[bold]Dry-run registration plan:[/bold]")
        console.print(f"  Course:      {course_number}")
        console.print(f"  Semester:    {semester}")
        console.print(f"  Preferences: {preferences or 'none (LVA registration)'}")
        console.print(f"  Watch:       {watch}")
        console.print(f"  Schedule:    {schedule}")
        console.print("\n[dim]No registration submitted (--dry-run).[/dim]")
        return

    if schedule:
        from datetime import UTC, datetime, timedelta

        from sophia.infra.persistence import connect_db, run_migrations
        from sophia.infra.scheduler import SchedulerError, create_scheduler

        async with http_session() as http:
            adapter = TissRegistrationAdapter(
                http=http,
                credentials=tiss_creds,
                host=settings.tiss_host,
            )
            target = await adapter.get_registration_status(course_number, semester)

        if not target.registration_start:
            console.print("[red]No registration start time found for this course.[/red]")
            raise SystemExit(1)

        reg_time = datetime.strptime(target.registration_start, "%d.%m.%Y %H:%M").replace(
            tzinfo=UTC
        )
        schedule_time = reg_time - timedelta(seconds=5)
        if schedule_time <= datetime.now(UTC):
            console.print("[yellow]Registration opens very soon or is already open.[/yellow]")
            console.print("[dim]Use --watch instead for immediate watching.[/dim]")
            raise SystemExit(1)

        cmd_parts = ["register", "go", course_number, "--watch"]
        if semester:
            cmd_parts.extend(["--semester", semester])
        if preferences:
            cmd_parts.extend(["--preferences", preferences])
        command = " ".join(cmd_parts)

        db = await connect_db(settings.db_path)
        try:
            await run_migrations(db)
            scheduler = create_scheduler(db)
            job = await scheduler.schedule(
                command,
                schedule_time,
                description=f"Register for {target.title or course_number}",
            )
        except SchedulerError as exc:
            console.print(f"[red]Failed to schedule: {exc}[/red]")
            raise SystemExit(1) from None
        finally:
            await db.close()

        console.print("\n[bold green]Job scheduled![/bold green]")
        console.print(f"  Job ID:    {job.job_id}")
        console.print(f"  Command:   sophia {command}")
        console.print(f"  Run at:    {job.scheduled_for}")
        console.print(f"  Opens at:  {target.registration_start}")
        console.print("\n[dim]Use [cyan]sophia jobs list[/cyan] to check status.[/dim]")
        return

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
