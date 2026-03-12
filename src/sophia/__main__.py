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

lectures_app = cyclopts.App(name="lectures", help="Hermes — Lecture knowledge base pipeline.")
app.command(lectures_app)

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
    """Log in to TUWEL and TISS via TU Wien SSO (single prompt)."""
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
async def groups(course_number: str, *, semester: str = "") -> None:
    """Show available groups for a course with day/time schedule."""
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
async def favorites(*, semester: str = "") -> None:
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
    from rich.console import Console
    from rich.table import Table

    from sophia.adapters.lecturetube import OpencastAdapter
    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app

    console = Console()

    try:
        async with create_app() as container:
            courses = await container.moodle.get_enrolled_courses()

            if not courses:
                console.print("[yellow]No enrolled courses found.[/yellow]")
                return

            console.print(f"[dim]Scanning {len(courses)} courses for lecture recordings...[/dim]\n")

            adapter = OpencastAdapter(
                http=container.http,
                host=container.settings.tuwel_host,
                moodle_session=container.moodle._moodle_session,  # pyright: ignore[reportPrivateUsage]
                cookie_name=container.moodle._cookie_name,  # pyright: ignore[reportPrivateUsage]
            )

            table = Table(title="Lecture Recordings")
            table.add_column("Course", style="cyan", no_wrap=False)
            table.add_column("Module", style="green", no_wrap=False)
            table.add_column("Episodes", justify="right")
            table.add_column("Module ID", style="dim")

            found_any = False
            for course in courses:
                sections = await container.moodle.get_course_content(course.id)
                for section in sections:
                    for module in section.modules:
                        if module.modname != "opencast":
                            continue
                        found_any = True
                        episodes = await adapter.get_series_episodes(module.id)
                        table.add_row(
                            course.shortname,
                            module.name,
                            str(len(episodes)),
                            str(module.id),
                        )

            if not found_any:
                console.print("[yellow]No lecture recordings found in enrolled courses.[/yellow]")
                return

            console.print(table)
            console.print(
                "\n[dim]Use [cyan]sophia lectures episodes <module-id>[/cyan]"
                " to list episodes for a module.[/dim]",
            )

    except AuthError:
        console.print("[red]Session expired — run:[/red] sophia auth login")
        raise SystemExit(1) from None


def main() -> None:
    """Entry point called by the `sophia` console script."""
    setup_logging(debug=True)
    app()


if __name__ == "__main__":
    main()
