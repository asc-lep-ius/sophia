"""CLI entry point for Sophia."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Annotated

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

register_app = cyclopts.App(
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
app.command(register_app)

lectures_app = cyclopts.App(name="lectures", help="Hermes — Lecture knowledge base pipeline.")
app.command(lectures_app)

jobs_app = cyclopts.App(name="jobs", help="Manage scheduled jobs.")
app.command(jobs_app)

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
async def login(*, save_credentials: bool = False) -> None:
    """Log in to TUWEL and TISS via TU Wien SSO (single prompt).

    Use --save-credentials to store your username/password in the OS
    keyring for automatic re-authentication in scheduled jobs.
    """
    import getpass
    import os

    from sophia.adapters.auth import (
        login_both,
        save_session,
        save_tiss_session,
        session_path,
        tiss_session_path,
    )
    from sophia.config import Settings

    settings = Settings()

    username = os.environ.get("SOPHIA_TUWEL_USERNAME") or input("TU Wien username: ")
    password = getpass.getpass("TU Wien password: ")

    tuwel_creds, tiss_creds = await login_both(
        settings.tuwel_host, settings.tiss_host, username, password
    )

    save_session(tuwel_creds, session_path(settings.config_dir))
    log.info("tuwel_login_complete", msg="TUWEL session saved.")

    if save_credentials:
        from sophia.adapters.auth import KeyringUnavailableError, save_credentials_to_keyring

        try:
            save_credentials_to_keyring(username, password)
        except KeyringUnavailableError:
            log.warning(
                "keyring_unavailable",
                msg="No keyring backend found. Credentials NOT saved. "
                "Install 'secretstorage' (Linux) or 'keyrings.alt' for file-based storage.",
            )

    if tiss_creds:
        save_tiss_session(tiss_creds, tiss_session_path(settings.config_dir))
        log.info("tiss_login_complete", msg="TISS session saved.")
    else:
        log.warning(
            "tiss_login_failed",
            msg="TUWEL login succeeded but TISS login failed. TISS features may be unavailable.",
        )


@auth_app.command
async def status() -> None:
    """Check if the current session is valid."""
    from urllib.parse import urlparse

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
        tuwel_domain = urlparse(settings.tuwel_host).hostname or ""
        http.cookies.set(creds.cookie_name, creds.moodle_session, domain=tuwel_domain)
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
    """Clear stored session credentials and keyring."""
    from sophia.adapters.auth import (
        clear_credentials_from_keyring,
        clear_session,
        clear_tiss_session,
        session_path,
        tiss_session_path,
    )
    from sophia.config import Settings

    settings = Settings()
    clear_session(session_path(settings.config_dir))
    clear_tiss_session(tiss_session_path(settings.config_dir))
    clear_credentials_from_keyring()
    log.info("logged_out", msg="Session and credentials cleared.")


# --- Kairos: TISS registration commands ---


def _require_tiss_session() -> tuple[Settings, TissSessionCredentials | None]:
    """Load TISS session or return (settings, None) if not logged in."""
    from sophia.adapters.auth import load_tiss_session, tiss_session_path
    from sophia.config import Settings

    settings = Settings()
    creds = load_tiss_session(tiss_session_path(settings.config_dir))
    return settings, creds


@register_app.command(name="status")
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


@register_app.command
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


@register_app.command
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


@register_app.command
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
    from rich.console import Console

    from sophia.adapters.tiss_registration import TissRegistrationAdapter
    from sophia.infra.http import http_session
    from sophia.services.registration import register_with_preferences, watch_and_register

    console = Console()
    settings, tiss_creds = _require_tiss_session()
    if tiss_creds is None:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1)

    if not semester:
        semester = _current_semester()

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


# --- Hermes: Lecture pipeline commands ---


@lectures_app.command(name="setup")
def lectures_setup() -> None:
    """Detect hardware and configure the lecture knowledge base pipeline."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    from sophia.config import Settings
    from sophia.domain.models import (
        ComputeDevice,
        ComputeType,
        EmbeddingProvider,
        HermesConfig,
        HermesEmbeddingConfig,
        HermesLLMConfig,
        HermesWhisperConfig,
        LLMProvider,
        WhisperModel,
    )
    from sophia.services.hermes_setup import (
        detect_gpu,
        get_provider_defaults,
        load_hermes_config,
        recommend_config,
        save_hermes_config,
        validate_llm_provider,
    )

    console = Console()
    settings = Settings()

    console.print(
        Panel("[bold]Hermes Setup Wizard[/bold]\nLecture knowledge base pipeline", style="cyan"),
    )

    # Step 1: Hardware detection
    console.print("\n[bold]Step 1:[/bold] Detecting hardware...")
    has_gpu, gpu_name, vram_mb = detect_gpu()

    if has_gpu:
        console.print(f"  [green]✓[/green] GPU detected: {gpu_name} ({vram_mb} MiB VRAM)")
    else:
        console.print("  [yellow]No GPU detected — using CPU mode[/yellow]")

    recommended = recommend_config(has_gpu, vram_mb)

    # Step 2: Whisper config
    console.print("\n[bold]Step 2:[/bold] Whisper transcription model")
    whisper_table = Table(show_header=True, box=None)
    whisper_table.add_column("#", style="dim", width=3)
    whisper_table.add_column("Model", style="cyan")
    whisper_table.add_column("Note")
    for i, m in enumerate(WhisperModel, 1):
        marker = " [green](recommended)[/green]" if m == recommended.whisper.model else ""
        whisper_table.add_row(str(i), m.value, marker)
    console.print(whisper_table)

    prompt = f"  Select model [1-{len(WhisperModel)}] (Enter for recommended): "
    whisper_choice = input(prompt).strip()
    models_list = list(WhisperModel)
    if whisper_choice and whisper_choice.isdigit():
        idx = int(whisper_choice) - 1
        if 0 <= idx < len(models_list):
            chosen_model = models_list[idx]
        else:
            chosen_model = recommended.whisper.model
    else:
        chosen_model = recommended.whisper.model

    if has_gpu:
        device = ComputeDevice.CUDA
        compute_type = ComputeType.FLOAT16
    else:
        device = ComputeDevice.CPU
        compute_type = ComputeType.FLOAT32

    whisper_cfg = HermesWhisperConfig(
        model=chosen_model,
        device=device,
        compute_type=compute_type,
    )

    # Step 3: LLM provider
    console.print("\n[bold]Step 3:[/bold] LLM provider")
    provider_table = Table(show_header=True, box=None)
    provider_table.add_column("#", style="dim", width=3)
    provider_table.add_column("Provider", style="cyan")
    provider_table.add_column("Default model")
    for i, p in enumerate(LLMProvider, 1):
        defaults = get_provider_defaults(p)
        provider_table.add_row(str(i), p.value, defaults["model"])
    console.print(provider_table)

    llm_choice = input(f"  Select provider [1-{len(LLMProvider)}] (Enter for GitHub): ").strip()
    providers_list = list(LLMProvider)
    if llm_choice and llm_choice.isdigit():
        idx = int(llm_choice) - 1
        if 0 <= idx < len(providers_list):
            chosen_provider = providers_list[idx]
        else:
            chosen_provider = LLMProvider.GITHUB
    else:
        chosen_provider = LLMProvider.GITHUB

    defaults = get_provider_defaults(chosen_provider)
    llm_cfg = HermesLLMConfig(
        provider=chosen_provider,
        model=defaults["model"],
        api_key_env=defaults["api_key_env"],
    )

    # Validate API key
    valid, msg = validate_llm_provider(llm_cfg)
    if valid:
        console.print(f"  [green]✓[/green] {msg}")
    else:
        console.print(f"  [yellow]⚠[/yellow] {msg}")

    # Step 4: Embeddings
    console.print("\n[bold]Step 4:[/bold] Embedding provider")
    embed_options: list[tuple[EmbeddingProvider, str]] = [
        (EmbeddingProvider.LOCAL, "intfloat/multilingual-e5-large"),
    ]
    # Add provider-specific embeddings if available
    if defaults["embedding_model"]:
        embed_provider = {
            LLMProvider.GITHUB: EmbeddingProvider.GITHUB,
            LLMProvider.GEMINI: EmbeddingProvider.GEMINI,
        }.get(chosen_provider)
        if embed_provider is not None:
            embed_options.append((embed_provider, defaults["embedding_model"]))

    for i, (ep, em) in enumerate(embed_options, 1):
        marker = " (recommended)" if i == 1 else ""
        console.print(f"  {i}. {ep.value} — {em}{marker}")

    prompt = f"  Select embeddings [1-{len(embed_options)}] (Enter for local): "
    embed_choice = input(prompt).strip()
    if embed_choice and embed_choice.isdigit():
        idx = int(embed_choice) - 1
        if 0 <= idx < len(embed_options):
            chosen_embed_provider, chosen_embed_model = embed_options[idx]
        else:
            chosen_embed_provider, chosen_embed_model = embed_options[0]
    else:
        chosen_embed_provider, chosen_embed_model = embed_options[0]

    embed_cfg = HermesEmbeddingConfig(provider=chosen_embed_provider, model=chosen_embed_model)

    config = HermesConfig(whisper=whisper_cfg, llm=llm_cfg, embeddings=embed_cfg)

    # Save
    path = save_hermes_config(config, settings.config_dir)
    console.print(f"\n[bold green]✓ Config saved to {path}[/bold green]")

    # Verify round-trip
    loaded = load_hermes_config(settings.config_dir)
    if loaded == config:
        console.print("[green]✓ Config verified[/green]")
    else:
        console.print("[red]⚠ Config verification failed — please check the file[/red]")

    console.print("\n[dim]Next steps:[/dim]")
    console.print("  1. Install Hermes extras: [cyan]uv pip install -e '.[hermes]'[/cyan]")
    console.print("  2. Process a lecture: [cyan]sophia lectures process <audio-file>[/cyan]")


@lectures_app.command(name="status")
def lectures_status() -> None:
    """Show current Hermes configuration."""
    from rich.console import Console
    from rich.table import Table

    from sophia.config import Settings
    from sophia.services.hermes_setup import load_hermes_config

    console = Console()
    settings = Settings()

    config = load_hermes_config(settings.config_dir)
    if config is None:
        console.print("[yellow]Hermes is not configured.[/yellow]")
        console.print("Run [cyan]sophia lectures setup[/cyan] to get started.")
        return

    table = Table(title="Hermes Configuration")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Whisper model", config.whisper.model.value)
    table.add_row("Device", config.whisper.device.value)
    table.add_row("Compute type", config.whisper.compute_type.value)
    table.add_row("VAD filter", str(config.whisper.vad_filter))
    table.add_row("Language", config.whisper.language)
    table.add_row("", "")
    table.add_row("LLM provider", config.llm.provider.value)
    table.add_row("LLM model", config.llm.model)
    table.add_row("API key env", config.llm.api_key_env or "(none)")
    table.add_row("", "")
    table.add_row("Embedding provider", config.embeddings.provider.value)
    table.add_row("Embedding model", config.embeddings.model)

    console.print(table)


@lectures_app.command(name="list")
async def lectures_list() -> None:
    """Discover lecture recordings from enrolled courses."""
    import asyncio
    from typing import TYPE_CHECKING

    from rich.console import Console
    from rich.table import Table

    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app

    if TYPE_CHECKING:
        from sophia.domain.models import ModuleInfo

    console = Console()

    try:
        async with create_app() as container:
            courses = await container.moodle.get_enrolled_courses()

            if not courses:
                console.print("[yellow]No enrolled courses found.[/yellow]")
                return

            console.print(f"[dim]Scanning {len(courses)} courses for lecture recordings...[/dim]\n")

            table = Table(title="Lecture Recordings")
            table.add_column("Course", style="cyan", no_wrap=False)
            table.add_column("Name", style="white", no_wrap=False)
            table.add_column("Module", style="green", no_wrap=False)
            table.add_column("Episodes", justify="right")
            table.add_column("Module ID", style="dim")

            sections_by_course = await asyncio.gather(
                *(container.moodle.get_course_content(c.id) for c in courses)
            )

            opencast_modules: list[tuple[str, str, ModuleInfo]] = []
            for course, sections in zip(courses, sections_by_course, strict=True):
                for section in sections:
                    for module in section.modules:
                        if module.modname == "opencast":
                            opencast_modules.append((course.shortname, course.fullname, module))

            if not opencast_modules:
                console.print("[yellow]No lecture recordings found in enrolled courses.[/yellow]")
                return

            episode_counts = await asyncio.gather(
                *(container.opencast.get_series_episodes(m.id) for _, _, m in opencast_modules)
            )

            for (shortname, fullname, module), episodes in zip(
                opencast_modules, episode_counts, strict=True
            ):
                table.add_row(
                    shortname,
                    fullname,
                    module.name,
                    str(len(episodes)),
                    str(module.id),
                )

            console.print(table)

    except AuthError:
        console.print("[red]Session expired — run:[/red] sophia auth login")
        raise SystemExit(1) from None


@lectures_app.command(name="download")
async def lectures_download(
    module_id: Annotated[
        int, cyclopts.Parameter(help="Opencast module ID (from 'sophia lectures list').")
    ],
) -> None:
    """Download lecture recordings. Prefers audio; extracts audio from video via ffmpeg."""
    from typing import TYPE_CHECKING

    from rich.console import Console
    from rich.progress import BarColumn, DownloadColumn, Progress, TransferSpeedColumn
    from rich.table import Table

    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app

    if TYPE_CHECKING:
        from sophia.domain.models import DownloadProgressEvent
    from sophia.services.hermes_download import download_lectures

    console = Console()

    try:
        async with create_app() as container:
            progress = Progress(
                "[progress.description]{task.description}",
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
            )
            tasks: dict[str, object] = {}

            def _on_progress(episode_id: str, event: DownloadProgressEvent) -> None:
                if episode_id not in tasks:
                    tasks[episode_id] = progress.add_task(episode_id, total=event.total_bytes)
                progress.update(tasks[episode_id], completed=event.bytes_downloaded)  # type: ignore[arg-type]

            with progress:
                results = await download_lectures(container, module_id, on_progress=_on_progress)

            table = Table(title="Download Results")
            table.add_column("Title", style="cyan", no_wrap=False)
            table.add_column("Status", style="white")
            table.add_column("File", style="dim", no_wrap=False)

            for r in results:
                status_style = {"completed": "green", "skipped": "yellow", "failed": "red"}.get(
                    r.status, "white"
                )
                table.add_row(
                    r.title,
                    f"[{status_style}]{r.status}[/{status_style}]",
                    str(r.file_path) if r.file_path else r.error or "",
                )

            console.print(table)

    except AuthError:
        console.print("[red]Session expired — run:[/red] sophia auth login")
        raise SystemExit(1) from None


@lectures_app.command(name="transcribe")
async def lectures_transcribe(
    module_id: Annotated[
        int, cyclopts.Parameter(help="Opencast module ID (from 'sophia lectures list').")
    ],
) -> None:
    """Transcribe downloaded lectures using Whisper. Requires 'sophia lectures setup'."""
    from rich.console import Console
    from rich.table import Table

    from sophia.domain.errors import AuthError, TranscriptionError
    from sophia.infra.di import create_app
    from sophia.services.hermes_transcribe import transcribe_lectures

    console = Console()

    try:
        async with create_app() as container:

            def _on_start(episode_id: str, title: str) -> None:
                console.print(f"[dim]Transcribing:[/dim] {title}...")

            def _on_complete(episode_id: str, segment_count: int) -> None:
                console.print(f"  [green]✓[/green] {segment_count} segments")

            results = await transcribe_lectures(
                container, module_id, on_start=_on_start, on_complete=_on_complete
            )

            table = Table(title="Transcription Results")
            table.add_column("Title", style="cyan", no_wrap=False)
            table.add_column("Status", style="white")
            table.add_column("Segments", justify="right")
            table.add_column("SRT", style="dim", no_wrap=False)

            for r in results:
                status_style = {
                    "completed": "green",
                    "skipped": "yellow",
                    "failed": "red",
                }.get(r.status, "white")
                table.add_row(
                    r.title,
                    f"[{status_style}]{r.status}[/{status_style}]",
                    str(r.segment_count) if r.segment_count else "",
                    str(r.srt_path) if r.srt_path else r.error or "",
                )

            console.print(table)

    except AuthError:
        console.print("[red]Session expired — run:[/red] sophia auth login")
        raise SystemExit(1) from None
    except TranscriptionError as exc:
        console.print(f"[red]Transcription error:[/red] {exc}")
        raise SystemExit(1) from None


# --- Jobs: scheduler management commands ---


@jobs_app.command(name="list")
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


@jobs_app.command
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


# --- Internal: job runner ---


@app.command(name="_run-job")
async def run_job(job_id: str) -> None:
    """Internal: Execute a scheduled job with auto-relogin. Not for direct use."""
    import shlex

    from sophia.config import Settings
    from sophia.domain.models import JobStatus
    from sophia.infra.persistence import connect_db, run_migrations
    from sophia.infra.scheduler import create_scheduler
    from sophia.services.job_runner import ensure_valid_session

    settings = Settings()
    db = await connect_db(settings.db_path)
    scheduler = None
    try:
        await run_migrations(db)
        scheduler = create_scheduler(db)

        job = await scheduler.get_job(job_id)
        if job is None:
            log.error("job_not_found", job_id=job_id)
            raise SystemExit(1)

        await scheduler.update_status(job_id, JobStatus.RUNNING)

        session_ok = await ensure_valid_session(
            settings.config_dir, settings.tuwel_host, settings.tiss_host
        )
        if not session_ok:
            log.error("job_failed_no_session", job_id=job_id)
            await scheduler.update_status(job_id, JobStatus.FAILED)
            raise SystemExit(1)

        command_tokens = shlex.split(job.command)
        log.info("job_executing", job_id=job_id, command=job.command)

        try:
            app(command_tokens)
        except SystemExit as exc:
            if exc.code and exc.code != 0:
                await scheduler.update_status(job_id, JobStatus.FAILED)
                raise

        await scheduler.update_status(job_id, JobStatus.COMPLETED)
        log.info("job_completed", job_id=job_id)
    except SystemExit:
        raise
    except Exception:
        log.error("job_failed", job_id=job_id, exc_info=True)
        if scheduler is not None:
            try:
                await scheduler.update_status(job_id, JobStatus.FAILED)
            except Exception:
                log.error("job_status_update_failed", job_id=job_id, exc_info=True)
        raise SystemExit(1) from None
    finally:
        await db.close()


def main() -> None:
    """Entry point called by the `sophia` console script."""
    setup_logging(debug=True)
    app()


if __name__ == "__main__":
    main()
