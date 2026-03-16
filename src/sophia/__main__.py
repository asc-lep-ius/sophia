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
    help_epilogue="Run 'sophia <command> --help' for details on any command.",
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

lectures_app = cyclopts.App(
    name="lectures",
    help=(
        "Hermes — Lecture knowledge base pipeline.\n"
        "\n"
        "Workflow:\n"
        " 1. setup                          — configure hardware and models\n"
        " 2. list                           — discover lecture recordings\n"
        " 3. download   MODULE_ID           — download recordings\n"
        " 4. transcribe MODULE_ID           — transcribe with Whisper\n"
        " 5. index      MODULE_ID           — build embedding index\n"
        ' 6. search     "query" MODULE_ID   — semantic search in transcripts\n'
        "\n"
        "Run setup once, then follow steps 2–6 for each course."
    ),
)
app.command(lectures_app)

jobs_app = cyclopts.App(name="jobs", help="Manage scheduled jobs.")
app.command(jobs_app)

study_app = cyclopts.App(
    name="study",
    help=(
        "Athena — Study companion and topic analysis.\n"
        "\n"
        "Workflow:\n"
        " 1. topics     MODULE_ID          — extract topics from lecture transcripts\n"
        " 2. confidence MODULE_ID          — rate your confidence per topic\n"
        " 3. session    MODULE_ID [TOPIC]  — guided study: pre-test → study → post-test\n"
        " 4. review     MODULE_ID [TOPIC]  — review flashcards with spaced repetition\n"
        " 5. explain    MODULE_ID [TOPIC]  — self-explain wrong answers\n"
        " 6. export     MODULE_ID          — export flashcards to Anki (.apkg)\n"
        " 7. due        [MODULE_ID]        — show topics due for review\n"
        "\n"
        "Requires Hermes lecture data. Run 'sophia lectures' pipeline first."
    ),
)
app.command(study_app)

# Shell completion (sophia --install-completion)
app.register_install_completion_command()  # type: ignore[reportUnknownMemberType]

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

            if not refs:
                console.print("[yellow]No book references found in enrolled courses.[/yellow]")
                return

            from sophia.services.pipeline import persist_references

            saved = await persist_references(container.db, refs)
    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None

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
    console.print(f"\n[dim]{saved} references persisted to database.[/dim]")


@auth_app.command
async def login(*, save_credentials: bool = False) -> None:
    """Log in to TUWEL and TISS via TU Wien SSO (single prompt).

    Use --save-credentials to store your username/password in the OS
    keyring for automatic re-authentication in scheduled jobs.
    """
    import getpass
    import os

    from rich.console import Console
    from rich.prompt import Prompt

    from sophia.adapters.auth import (
        login_both,
        save_session,
        save_tiss_session,
        session_path,
        tiss_session_path,
    )
    from sophia.config import Settings

    console = Console()
    settings = Settings()

    username = os.environ.get("SOPHIA_TUWEL_USERNAME") or Prompt.ask(
        "TU Wien username", console=console
    )
    password = getpass.getpass("TU Wien password: ")

    tuwel_creds, tiss_creds = await login_both(
        settings.tuwel_host, settings.tiss_host, username, password
    )

    save_session(tuwel_creds, session_path(settings.config_dir))
    console.print("[green]TUWEL session saved.[/green]")

    if save_credentials:
        from sophia.adapters.auth import KeyringUnavailableError, save_credentials_to_keyring

        try:
            save_credentials_to_keyring(username, password)
        except KeyringUnavailableError:
            console.print(
                "[yellow]No keyring backend found. Credentials NOT saved.[/yellow]\n"
                "Install 'secretstorage' (Linux) or 'keyrings.alt' for file-based storage."
            )

    if tiss_creds:
        save_tiss_session(tiss_creds, tiss_session_path(settings.config_dir))
        console.print("[green]TISS session saved.[/green]")
    else:
        console.print(
            "[yellow]TUWEL login succeeded but TISS login failed. "
            "TISS features may be unavailable.[/yellow]"
        )


@auth_app.command
async def status() -> None:
    """Check if the current session is valid."""
    from urllib.parse import urlparse

    from rich.console import Console

    from sophia.adapters.auth import load_session, session_path
    from sophia.adapters.moodle import MoodleAdapter
    from sophia.config import Settings
    from sophia.domain.errors import AuthError
    from sophia.infra.http import http_session

    console = Console()
    settings = Settings()
    creds = load_session(session_path(settings.config_dir))
    if creds is None:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
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
            console.print("[green]Session is active.[/green]")
        except AuthError:
            console.print("[red]Not logged in — run:[/red] sophia auth login")
            raise SystemExit(1) from None


@auth_app.command
def logout() -> None:
    """Clear stored session credentials and keyring."""
    from rich.console import Console

    from sophia.adapters.auth import (
        clear_credentials_from_keyring,
        clear_session,
        clear_tiss_session,
        session_path,
        tiss_session_path,
    )
    from sophia.config import Settings

    console = Console()
    settings = Settings()
    clear_session(session_path(settings.config_dir))
    clear_tiss_session(tiss_session_path(settings.config_dir))
    clear_credentials_from_keyring()
    console.print("[green]Session and credentials cleared.[/green]")


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
    from rich.prompt import Confirm
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

    from sophia.services.hermes_setup import check_hermes_deps, install_hermes_extras

    missing = check_hermes_deps()
    if not missing:
        console.print("\n[bold green]✓ Hermes dependencies already installed[/bold green]")
    else:
        console.print(f"\n[yellow]Missing Hermes dependencies: {', '.join(missing)}[/yellow]")
        if Confirm.ask("Install Hermes dependencies now?", default=True, console=console):
            console.print("[dim]Installing sophia[hermes]… (output streamed below)[/dim]")
            ok, msg = install_hermes_extras()
            if ok:
                console.print("[bold green]✓ Hermes dependencies installed[/bold green]")
            else:
                console.print(f"[red]Installation failed:[/red] {msg}")
        else:
            console.print("\n[dim]Manual install:[/dim]")
            console.print("  [cyan]uv pip install -e '.[hermes]'[/cyan]")

    console.print("\n[dim]Next step:[/dim]")
    console.print("  [cyan]sophia lectures list[/cyan]")


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
            console.print(
                "\n[dim]Next step:[/dim] [cyan]sophia lectures download <module-id>[/cyan]"
            )

    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
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
            console.print(
                "\n[dim]Next step:[/dim] [cyan]sophia lectures transcribe <module-id>[/cyan]"
            )

    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
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
            console.print("\n[dim]Next step:[/dim] [cyan]sophia lectures index <module-id>[/cyan]")

    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None
    except TranscriptionError as exc:
        console.print(f"[red]Transcription error:[/red] {exc}")
        raise SystemExit(1) from None


@lectures_app.command(name="index")
async def lectures_index(
    module_id: Annotated[
        int, cyclopts.Parameter(help="Opencast module ID (from 'sophia lectures list').")
    ],
) -> None:
    """Build search index from transcribed lectures. Requires transcription first."""
    from rich.console import Console
    from rich.table import Table

    from sophia.domain.errors import AuthError, EmbeddingError
    from sophia.infra.di import create_app
    from sophia.services.hermes_index import index_lectures

    console = Console()

    try:
        async with create_app() as container:

            def _on_start(episode_id: str, title: str) -> None:
                console.print(f"[dim]Indexing:[/dim] {title}...")

            def _on_complete(episode_id: str, chunk_count: int) -> None:
                console.print(f"  [green]✓[/green] {chunk_count} chunks")

            results = await index_lectures(
                container, module_id, on_start=_on_start, on_complete=_on_complete
            )

            table = Table(title="Indexing Results")
            table.add_column("Title", style="cyan", no_wrap=False)
            table.add_column("Status", style="white")
            table.add_column("Chunks", justify="right")

            for r in results:
                status_style = {
                    "completed": "green",
                    "skipped": "yellow",
                    "failed": "red",
                }.get(r.status, "white")
                table.add_row(
                    r.title,
                    f"[{status_style}]{r.status}[/{status_style}]",
                    str(r.chunk_count) if r.chunk_count else r.error or "",
                )

            console.print(table)
            console.print(
                '\n[dim]Next step:[/dim] [cyan]sophia lectures search "query" <module-id>[/cyan]'
            )

    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None
    except EmbeddingError as exc:
        console.print(f"[red]Embedding error:[/red] {exc}")
        raise SystemExit(1) from None


@lectures_app.command(name="search")
async def lectures_search(
    query: Annotated[str, cyclopts.Parameter(help="Natural language search query.")],
    module_id: Annotated[int, cyclopts.Parameter(help="Opencast module ID to search within.")],
    *,
    count: Annotated[
        int, cyclopts.Parameter(help="Number of results.", name=["--count", "-n"])
    ] = 5,
) -> None:
    """Search lecture transcripts by semantic similarity."""
    from rich.console import Console
    from rich.panel import Panel

    from sophia.domain.errors import AuthError, EmbeddingError
    from sophia.infra.di import create_app
    from sophia.services.hermes_index import search_lectures

    console = Console()

    try:
        async with create_app() as container:
            results = await search_lectures(container, module_id, query, n_results=count)

            if not results:
                console.print("[yellow]No results found.[/yellow]")
                return

            for i, r in enumerate(results, 1):
                start_mm, start_ss = divmod(int(r.start_time), 60)
                end_mm, end_ss = divmod(int(r.end_time), 60)
                header = (
                    f"[cyan]{r.title}[/cyan]  "
                    f"[dim]{start_mm:02d}:{start_ss:02d} – {end_mm:02d}:{end_ss:02d}[/dim]  "
                    f"[green]score: {r.score:.2f}[/green]"
                )
                console.print(Panel(r.chunk_text, title=f"Result {i}", subtitle=header))

    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None
    except EmbeddingError as exc:
        console.print(f"[red]Embedding error:[/red] {exc}")
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


@app.command(name="_run-job", group=cyclopts.Group("Internal", show=False))
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


# ---------------------------------------------------------------------------
# Athena — Quiz / Study companion
# ---------------------------------------------------------------------------


@study_app.command(name="topics")
async def study_topics(
    module_id: Annotated[int, cyclopts.Parameter(help="Opencast module ID.")],
) -> None:
    """Extract topics from lecture transcripts and cross-reference with lectures."""
    from rich.console import Console
    from rich.status import Status
    from rich.table import Table

    from sophia.domain.errors import AuthError, EmbeddingError, TopicExtractionError
    from sophia.infra.di import create_app
    from sophia.services.athena_study import (
        extract_topics_from_lectures,
        link_topics_to_lectures,
    )

    console = Console()

    try:
        async with create_app() as container:
            with Status("Extracting topics from lectures…", console=console):
                topics = await extract_topics_from_lectures(container, module_id)

            if not topics:
                console.print(
                    "[yellow]No topics extracted. Ensure lectures are indexed first.[/yellow]"
                )
                console.print("  Run: sophia lectures download/transcribe/index <module-id>")
                return

            console.print(f"[green]Extracted {len(topics)} topics.[/green]\n")

            topic_labels = [t.topic for t in topics]
            with Status("Cross-referencing with lecture content…", console=console):
                links = await link_topics_to_lectures(
                    container,
                    module_id,
                    module_id,
                    topic_labels,
                )

            # Build episode title mapping for display
            episode_ids: set[str] = set()
            for chunks in links.values():
                for chunk, _score in chunks:
                    episode_ids.add(chunk.episode_id)

            title_map: dict[str, str] = {}
            if episode_ids:
                placeholders = ",".join("?" for _ in episode_ids)
                cursor = await container.db.execute(
                    f"SELECT episode_id, title FROM lecture_downloads"  # noqa: S608
                    f" WHERE episode_id IN ({placeholders})",
                    tuple(episode_ids),
                )
                for row in await cursor.fetchall():
                    title_map[row[0]] = row[1]

            table = Table(title="Topic Analysis")
            table.add_column("Topic", style="cyan")
            table.add_column("Freq", justify="right")
            table.add_column("Lecture Coverage", style="dim")

            for tm in topics:
                lecture_refs: list[str] = []
                for chunk, _score in links.get(tm.topic, [])[:3]:
                    title = title_map.get(chunk.episode_id, "Unknown")
                    mm, ss = divmod(int(chunk.start_time), 60)
                    lecture_refs.append(f"{title} ({mm:02d}:{ss:02d})")
                coverage = ", ".join(lecture_refs) if lecture_refs else "⚠ No lecture match"
                table.add_row(tm.topic, str(tm.frequency), coverage)

            console.print(table)

            # Show recommended reading from discovered references
            from sophia.services.pipeline import get_course_references

            series_title = ""
            cursor = await container.db.execute(
                "SELECT DISTINCT title FROM lecture_downloads WHERE module_id = ? LIMIT 1",
                (module_id,),
            )
            row = await cursor.fetchone()
            if row:
                series_title = row[0].split(" - ")[0].split(" – ")[0].strip() if row[0] else ""

            reading = (
                await get_course_references(container.db, course_name=series_title)
                if series_title
                else []
            )
            if reading:
                reading_table = Table(title="Recommended Reading")
                reading_table.add_column("Title", style="cyan", no_wrap=False)
                reading_table.add_column("Author(s)", style="green")
                reading_table.add_column("ISBN", style="magenta")
                reading_table.add_column("Source", style="blue")
                for ref in reading:
                    reading_table.add_row(
                        ref.title or "—",
                        ", ".join(ref.authors) if ref.authors else "—",
                        ref.isbn or "—",
                        ref.source.value,
                    )
                console.print(reading_table)
            else:
                console.print(
                    "\n[dim]No reading material found. Run:[/dim] "
                    "[cyan]sophia books discover[/cyan] [dim]to find course books.[/dim]"
                )

            console.print("\n[dim]Next:[/dim] [cyan]sophia study confidence <module-id>[/cyan]")

    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None
    except TopicExtractionError as exc:
        console.print(f"[red]Topic extraction failed:[/red] {exc}")
        raise SystemExit(1) from None
    except EmbeddingError as exc:
        console.print(f"[red]Embedding error:[/red] {exc}")
        raise SystemExit(1) from None


@study_app.command(name="confidence")
async def study_confidence(
    module_id: Annotated[
        int, cyclopts.Parameter(help="Opencast module ID (same as used in topics).")
    ],
) -> None:
    """Rate your confidence per topic — discover blind spots through calibration."""
    from rich.console import Console
    from rich.prompt import IntPrompt
    from rich.table import Table

    from sophia.domain.errors import AuthError, ConfidenceError
    from sophia.infra.di import create_app
    from sophia.services.athena_confidence import (
        format_calibration_feedback,
        get_confidence_ratings,
        rate_confidence,
    )
    from sophia.services.athena_study import get_course_topics

    console = Console()

    try:
        async with create_app() as container:
            topics = await get_course_topics(container, module_id)

            if not topics:
                console.print("[yellow]No topics found. Run 'sophia study topics' first.[/yellow]")
                return

            console.print(
                "[bold]Rate your confidence for each topic (1-5):[/bold]\n"
                "  1 = No idea  2 = Vague  3 = Somewhat  4 = Good  5 = Confident\n"
            )

            for tm in topics:
                rating = IntPrompt.ask(
                    f"  {tm.topic}",
                    choices=["1", "2", "3", "4", "5"],
                    default=3,
                    console=console,
                )
                await rate_confidence(container, tm.topic, module_id, rating)

            console.print()

            all_ratings = await get_confidence_ratings(container.db, module_id)

            table = Table(title="Confidence Assessment")
            table.add_column("Topic", style="cyan")
            table.add_column("Predicted", justify="right")
            table.add_column("Actual", justify="right")
            table.add_column("Status")

            for r in all_ratings:
                predicted_str = f"{r.predicted:.0%}"
                actual_str = f"{r.actual:.0%}" if r.actual is not None else "—"

                err = r.calibration_error
                if err is None:
                    status = "⏳ Pending"
                elif abs(err) <= 0.1:
                    status = "✅ Calibrated"
                elif err > 0.2:
                    status = "🔍 Blind spot"
                elif err > 0:
                    status = "📈 Slightly over"
                elif err < -0.2:
                    status = "💪 Underestimate"
                else:
                    status = "📉 Slightly under"

                table.add_row(r.topic, predicted_str, actual_str, status)

            console.print(table)

            has_actual = [r for r in all_ratings if r.actual is not None]
            if has_actual:
                console.print("\n[bold]Calibration Feedback:[/bold]")
                for r in has_actual:
                    console.print(format_calibration_feedback(r))
            else:
                console.print(
                    "\n[dim]Actual scores will appear after you study and review cards.[/dim]"
                )

            console.print(
                "\n[dim]Next:[/dim] [cyan]sophia study session <module-id> [topic][/cyan]"
            )

    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None
    except ConfidenceError as exc:
        console.print(f"[red]Confidence assessment failed:[/red] {exc}")
        raise SystemExit(1) from None


@study_app.command(name="session")
async def study_session(
    module_id: Annotated[int, cyclopts.Parameter(help="Opencast module ID.")],
    topic: Annotated[
        str | None, cyclopts.Parameter(help="Topic to study. Defaults to weakest.")
    ] = None,
) -> None:
    """Guided study: pre-test → lecture review → post-test → flashcard creation."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.status import Status

    from sophia.domain.errors import AuthError, StudySessionError, TopicExtractionError
    from sophia.infra.di import create_app
    from sophia.services.athena_study import (
        complete_study_session,
        generate_study_questions,
        get_course_topics,
        save_flashcard,
        start_study_session,
    )

    console = Console()

    try:
        async with create_app() as container:
            # --- Load topics ---
            topics = await get_course_topics(container, module_id)
            if not topics:
                console.print("[yellow]No topics found. Run 'sophia study topics' first.[/yellow]")
                return

            # --- Select topic ---
            if topic is None:
                # Try to pick weakest blind spot, otherwise first topic
                try:
                    from sophia.services.athena_confidence import get_blind_spots

                    blind_spots = await get_blind_spots(container.db, module_id)
                    if blind_spots:
                        topic = blind_spots[0].topic
                        console.print(f"[dim]Auto-selected blind spot:[/dim] [bold]{topic}[/bold]")
                except Exception:
                    pass
                if topic is None:
                    topic = topics[0].topic
                    console.print(f"[dim]Auto-selected first topic:[/dim] [bold]{topic}[/bold]")

            console.print(f"\n[bold]📚 Study Session: {topic}[/bold]\n")

            # --- Start session ---
            session = await start_study_session(container.db, module_id, topic)

            # --- PRE-TEST ---
            console.print("[bold cyan]Phase 1: Pre-Test[/bold cyan]")
            try:
                with Status("Generating pre-test questions…", console=console):
                    pre_questions = await generate_study_questions(
                        container, module_id, topic, count=3
                    )
            except TopicExtractionError:
                console.print("[yellow]LLM unavailable — using generic questions.[/yellow]")
                pre_questions = [f"Explain the concept of {topic} in your own words."] * 3

            pre_correct = 0
            for i, q in enumerate(pre_questions, 1):
                console.print(f"\n  [bold]Q{i}:[/bold] {q}")
                answer = Prompt.ask("  Your answer (or 'skip')", default="skip", console=console)
                if answer.strip().lower() == "skip":
                    continue
                self_grade = Confirm.ask("  Did you get it right?", default=False, console=console)
                if self_grade:
                    pre_correct += 1

            pre_score = pre_correct / len(pre_questions) if pre_questions else 0.0
            console.print(
                f"\n  Pre-test score: [bold]{pre_score:.0%}[/bold]"
                f" ({pre_correct}/{len(pre_questions)})"
            )

            if not Confirm.ask("\nContinue to study phase?", default=True, console=console):
                await complete_study_session(container.db, session.id, pre_score, pre_score)
                console.print("[dim]Session saved with pre-test only.[/dim]")
                return

            # --- STUDY PHASE ---
            console.print("\n[bold cyan]Phase 2: Lecture Review[/bold cyan]")
            with Status("Fetching lecture content…", console=console):
                from sophia.services.athena_study import get_lecture_context

                lecture_text = await get_lecture_context(container, module_id, topic)

            if lecture_text:
                console.print(
                    Panel(
                        lecture_text[:2000],
                        title=f"Lecture Notes: {topic}",
                        expand=False,
                    )
                )
            else:
                console.print("[yellow]No lecture content found for this topic.[/yellow]")

            if not Confirm.ask("\nContinue to post-test?", default=True, console=console):
                await complete_study_session(container.db, session.id, pre_score, pre_score)
                console.print("[dim]Session saved with pre-test only.[/dim]")
                return

            # --- POST-TEST ---
            console.print("\n[bold cyan]Phase 3: Post-Test[/bold cyan]")
            try:
                with Status("Generating post-test questions…", console=console):
                    post_questions = await generate_study_questions(
                        container, module_id, topic, count=3
                    )
            except TopicExtractionError:
                post_questions = [f"Explain the concept of {topic} in your own words."] * 3

            post_correct = 0
            for i, q in enumerate(post_questions, 1):
                console.print(f"\n  [bold]Q{i}:[/bold] {q}")
                answer = Prompt.ask("  Your answer (or 'skip')", default="skip", console=console)
                if answer.strip().lower() == "skip":
                    continue
                self_grade = Confirm.ask("  Did you get it right?", default=False, console=console)
                if self_grade:
                    post_correct += 1

            post_score = post_correct / len(post_questions) if post_questions else 0.0
            console.print(
                f"\n  Post-test score: [bold]{post_score:.0%}[/bold]"
                f" ({post_correct}/{len(post_questions)})"
            )

            # --- Show improvement ---
            improvement = post_score - pre_score
            if improvement > 0:
                console.print(f"\n  [green]📈 Improvement: +{improvement:.0%}[/green]")
            elif improvement < 0:
                console.print(f"\n  [yellow]📉 Change: {improvement:.0%}[/yellow]")
            else:
                console.print("\n  [dim]➡ No change in score.[/dim]")

            # --- Complete session ---
            await complete_study_session(container.db, session.id, pre_score, post_score)

            # --- Optional flashcard creation ---
            if Confirm.ask("\nCreate a flashcard for this topic?", default=True, console=console):
                front = Prompt.ask("  Front (question)", console=console)
                back = Prompt.ask("  Back (answer)", console=console)
                if front.strip() and back.strip():
                    await save_flashcard(
                        container.db, module_id, topic, front.strip(), back.strip()
                    )
                    console.print("[green]✅ Flashcard saved![/green]")
                else:
                    console.print("[dim]Skipped — empty flashcard.[/dim]")

            console.print("\n[bold green]✅ Study session complete![/bold green]")
            console.print("\n[dim]Next:[/dim] [cyan]sophia study review <module-id> [topic][/cyan]")

    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None
    except TopicExtractionError as exc:
        console.print(f"[yellow]LLM unavailable:[/yellow] {exc}")
        console.print("Study with lecture material directly instead.")
        raise SystemExit(1) from None
    except StudySessionError as exc:
        console.print(f"[red]Study session error:[/red] {exc}")
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        console.print("\n[dim]Session interrupted — partial progress saved.[/dim]")


@study_app.command(name="review")
async def study_review(
    module_id: Annotated[int, cyclopts.Parameter(help="Opencast module ID.")],
    topic: Annotated[
        str | None, cyclopts.Parameter(help="Topic to review. Defaults to all.")
    ] = None,
    count: Annotated[int, cyclopts.Parameter(help="Max cards to review.")] = 10,
) -> None:
    """Review flashcards and auto-calibrate confidence from results."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.table import Table

    from sophia.domain.errors import AuthError, CardReviewError
    from sophia.infra.di import create_app
    from sophia.services.athena_study import (
        get_due_cards,
        get_review_stats,
        save_review_attempt,
        update_topic_calibration,
    )

    console = Console()

    try:
        async with create_app() as container:
            cards = await get_due_cards(container.db, module_id, topic=topic, limit=count)

            if not cards:
                console.print(
                    "[yellow]No flashcards to review. "
                    "Create some with 'sophia study session' first.[/yellow]"
                )
                return

            console.print(f"\n[bold]🃏 Card Review: {len(cards)} card(s)[/bold]\n")

            correct = 0
            reviewed_topics: set[str] = set()

            for i, card in enumerate(cards, 1):
                console.print(Panel(card.front, title=f"Card {i}/{len(cards)} — {card.topic}"))
                Prompt.ask("Press Enter to reveal answer", default="", console=console)
                console.print(Panel(card.back, title="Answer", style="green"))

                success = Confirm.ask("Did you get it right?", default=False, console=console)
                if success:
                    correct += 1

                await save_review_attempt(container.db, flashcard_id=card.id, success=success)
                reviewed_topics.add(card.topic)
                console.print()

            # Calibrate all reviewed topics
            for t in reviewed_topics:
                await update_topic_calibration(container.db, course_id=module_id, topic=t)

            # Summary
            accuracy = correct / len(cards) if cards else 0.0
            console.print("[bold]📊 Review Complete[/bold]")
            console.print(f"  Total: {len(cards)}  Correct: {correct}  Accuracy: {accuracy:.0%}\n")

            table = Table(title="Per-Topic Breakdown")
            table.add_column("Topic", style="cyan")
            table.add_column("Reviews", justify="right")
            table.add_column("Correct", justify="right")
            table.add_column("Rate", justify="right")

            for t in sorted(reviewed_topics):
                stats = await get_review_stats(container.db, module_id, topic=t)
                table.add_row(
                    t,
                    str(stats["total_reviews"]),
                    str(stats["success_count"]),
                    f"{stats['success_rate']:.0%}",
                )

            console.print(table)
            console.print(
                "\n[dim]Next:[/dim] [cyan]sophia study explain <module-id> [topic][/cyan]"
            )

    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None
    except CardReviewError as exc:
        console.print(f"[red]Card review error:[/red] {exc}")
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        console.print("\n[dim]Review interrupted — partial progress saved.[/dim]")


@study_app.command(name="explain")
async def study_explain(
    module_id: Annotated[int, cyclopts.Parameter(help="Opencast module ID.")],
    topic: Annotated[
        str | None, cyclopts.Parameter(help="Topic to filter. Defaults to all.")
    ] = None,
    count: Annotated[int, cyclopts.Parameter(help="Max cards to explain.")] = 5,
) -> None:
    """Self-explain wrong answers with fading scaffolds."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt

    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app
    from sophia.services.athena_study import (
        get_explanation_count,
        get_failed_review_cards,
        get_lecture_context,
        get_scaffold_level,
        get_scaffold_prompts,
        save_self_explanation,
    )

    console = Console()

    try:
        async with create_app() as container:
            cards = await get_failed_review_cards(container.db, module_id, topic=topic, limit=count)

            if not cards:
                console.print(
                    "[yellow]No wrong answers to explain. "
                    "Review cards with 'sophia study review' first.[/yellow]"
                )
                return

            exp_count = await get_explanation_count(container.db, module_id)
            level = get_scaffold_level(exp_count)
            prompts = get_scaffold_prompts(level)

            scaffold_labels = {3: "full", 1: "minimal", 0: "open"}
            console.print(
                f"\n[bold]🧠 Self-Explanation: {len(cards)} card(s), "
                f"scaffold={scaffold_labels.get(level, str(level))}[/bold]\n"
            )

            saved = 0
            for i, card in enumerate(cards, 1):
                console.print(Panel(card.front, title=f"Card {i}/{len(cards)} — {card.topic}"))
                console.print(Panel(card.back, title="Correct Answer", style="green"))

                # Collect explanation based on scaffold level
                parts: list[str] = []
                if prompts:
                    for prompt_text in prompts:
                        answer = Prompt.ask(f"[cyan]{prompt_text}[/cyan]", console=console)
                        parts.append(answer)
                else:
                    answer = Prompt.ask("[cyan]Explain in your own words:[/cyan]", console=console)
                    parts.append(answer)

                explanation_text = "\n".join(parts)

                await save_self_explanation(
                    container.db,
                    flashcard_id=card.id,
                    student_explanation=explanation_text,
                    scaffold_level=level,
                )
                saved += 1

                # Show lecture context
                context = await get_lecture_context(container, module_id, card.topic)
                if context:
                    console.print(Panel(context, title="Lecture Context", style="dim"))
                console.print()

            console.print(
                f"[bold]✅ {saved} explanation(s) recorded (scaffold level {level})[/bold]"
            )

    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        console.print("\n[dim]Explanation interrupted — partial progress saved.[/dim]")


@study_app.command(name="export")
async def study_export(
    module_id: Annotated[int, cyclopts.Parameter(help="Opencast module ID.")],
    *,
    output: Annotated[str | None, cyclopts.Parameter(help="Output .apkg file path.")] = None,
    blocked: Annotated[
        bool, cyclopts.Parameter(help="Group cards by topic instead of interleaving.")
    ] = False,
    deck_name: Annotated[str | None, cyclopts.Parameter(help="Custom Anki deck name.")] = None,
) -> None:
    """Export flashcards as an Anki .apkg deck."""
    from pathlib import Path

    from rich.console import Console
    from rich.panel import Panel

    from sophia.domain.errors import AthenaError
    from sophia.infra.di import create_app
    from sophia.services.athena_export import export_anki_deck

    console = Console()
    out_path = Path(output or f"sophia-{module_id}.apkg")

    try:
        async with create_app() as container:
            count = await export_anki_deck(
                container.db,
                module_id,
                out_path,
                interleaved=not blocked,
                deck_name=deck_name,
            )

            if count == 0:
                console.print("[yellow]No flashcards found for this module.[/yellow]")
            else:
                order = "blocked (by topic)" if blocked else "interleaved (shuffled)"
                console.print(
                    Panel(
                        f"Exported [bold]{count}[/bold] cards to [cyan]{out_path}[/cyan]\n"
                        f"Card order: {order}",
                        title="Anki Export",
                        style="green",
                    )
                )

    except AthenaError as exc:
        console.print(f"[red]Export failed:[/red] {exc}")
        raise SystemExit(1) from None


@study_app.command(name="due")
async def study_due(
    module_id: Annotated[
        int | None, cyclopts.Parameter(help="Opencast module ID. Omit for all courses.")
    ] = None,
) -> None:
    """Show topics due for spaced review and upcoming reviews."""
    from rich.console import Console
    from rich.table import Table

    from sophia.infra.di import create_app
    from sophia.services.athena_review import get_due_reviews, get_upcoming_reviews

    console = Console()

    async with create_app() as container:
        course_id = module_id
        due = await get_due_reviews(container.db, course_id=course_id)
        upcoming = await get_upcoming_reviews(container.db, course_id=course_id, days_ahead=3)

        if not due and not upcoming:
            console.print(
                "[yellow]No reviews scheduled. "
                "Start studying with:[/yellow] sophia study session <module-id>"
            )
            return

        if due:
            table = Table(title="Reviews Due Today", show_lines=True)
            table.add_column("Topic", style="bold")
            table.add_column("Course", justify="right")
            table.add_column("Review #", justify="center")
            table.add_column("Last Score", justify="center")

            for sched in due:
                score = sched.score_at_last_review
                if score is None:
                    status = "[dim]new[/dim]"
                elif score >= 0.8:
                    status = f"[green]{score:.0%} advancing[/green]"
                elif score >= 0.5:
                    status = f"[yellow]{score:.0%} repeating[/yellow]"
                else:
                    status = f"[red]{score:.0%} reset![/red]"

                table.add_row(
                    sched.topic,
                    str(sched.course_id),
                    str(sched.interval_index + 1),
                    status,
                )
            console.print(table)

        if upcoming:
            table = Table(title="Upcoming Reviews (next 3 days)", show_lines=True)
            table.add_column("Topic", style="bold")
            table.add_column("Course", justify="right")
            table.add_column("Due", justify="center")
            table.add_column("Interval", justify="center")

            for sched in upcoming:
                table.add_row(
                    sched.topic,
                    str(sched.course_id),
                    sched.next_review_at[:10],
                    f"{sched.interval_days}d",
                )
            console.print(table)


def main() -> None:
    """Entry point called by the `sophia` console script."""
    setup_logging(debug=True)
    app()


if __name__ == "__main__":
    main()
