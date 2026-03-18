"""Hermes — Lecture knowledge base pipeline commands."""

from __future__ import annotations

from typing import Annotated

import cyclopts

app = cyclopts.App(
    name="lectures",
    help=(
        "Hermes — Lecture knowledge base pipeline.\n"
        "\n"
        "Workflow:\n"
        " 1. setup                          — configure hardware and models\n"
        " 2. list                           — discover lecture recordings\n"
        " 3. process    MODULE_ID           — full pipeline (all stages)\n"
        " 4. download   MODULE_ID           — download recordings only\n"
        " 5. transcribe MODULE_ID           — transcribe with Whisper\n"
        " 6. index      MODULE_ID           — build embedding index\n"
        ' 7. search     "query" MODULE_ID   — semantic search in transcripts\n'
        "\n"
        "Run setup once, then use 'process' for the full pipeline or steps 4–7 individually."
    ),
)


@app.command(name="setup")
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


@app.command(name="status")
async def lectures_status(
    module_id: Annotated[
        str | None,
        cyclopts.Parameter(
            help="Module ID, course number (186.813), or name. Omit to show config."
        ),
    ] = None,
) -> None:
    """Show Hermes configuration or per-episode pipeline status for a module."""
    from rich.console import Console
    from rich.table import Table

    from sophia.config import Settings
    from sophia.services.hermes_setup import load_hermes_config

    console = Console()
    settings = Settings()

    if module_id is None:
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
        return

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.infra.di import create_app
    from sophia.services.hermes_manage import get_pipeline_status

    async with create_app() as container:
        async with handle_resolve_error():
            resolved_id = await resolve_module_id(module_id, container.moodle)
        statuses = await get_pipeline_status(container.db, resolved_id)

    if not statuses:
        console.print(f"[yellow]No episodes found for module {resolved_id}.[/yellow]")
        return

    table = Table(title=f"Pipeline Status — Module {resolved_id}")
    table.add_column("Episode ID", style="dim", max_width=12)
    table.add_column("Title", style="cyan")
    table.add_column("Download", style="green")
    table.add_column("Transcription", style="green")
    table.add_column("Index", style="green")
    table.add_column("Skip Reason", style="yellow")

    for ep in statuses:
        table.add_row(
            ep.episode_id[:12],
            ep.title,
            ep.download_status,
            ep.transcription_status or "—",
            ep.index_status or "—",
            ep.skip_reason or "",
        )

    console.print(table)


@app.command(name="discard")
async def lectures_discard(
    module_id: Annotated[
        str, cyclopts.Parameter(help="Module ID, course number (186.813), or name.")
    ],
    episode_id: Annotated[str, cyclopts.Parameter(help="Episode ID to discard.")],
) -> None:
    """Mark an episode as discarded, preventing further processing."""
    from rich.console import Console

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.infra.di import create_app
    from sophia.services.hermes_manage import discard_episode

    console = Console()

    async with create_app() as container:
        async with handle_resolve_error():
            resolved_id = await resolve_module_id(module_id, container.moodle)
        ok = await discard_episode(container.db, resolved_id, episode_id)

    if ok:
        console.print(f"[green]Episode {episode_id} discarded.[/green]")
    else:
        console.print(
            f"[red]Episode {episode_id} not found in module {resolved_id} "
            f"(or not in a discardable state).[/red]"
        )
        raise SystemExit(1)


@app.command(name="restore")
async def lectures_restore(
    module_id: Annotated[
        str, cyclopts.Parameter(help="Module ID, course number (186.813), or name.")
    ],
    episode_id: Annotated[str, cyclopts.Parameter(help="Episode ID to restore.")],
) -> None:
    """Undo discard — re-queue an episode for processing."""
    from rich.console import Console

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.infra.di import create_app
    from sophia.services.hermes_manage import restore_episode

    console = Console()

    async with create_app() as container:
        async with handle_resolve_error():
            resolved_id = await resolve_module_id(module_id, container.moodle)
        ok = await restore_episode(container.db, resolved_id, episode_id)

    if ok:
        console.print(f"[green]Episode {episode_id} restored to queue.[/green]")
    else:
        console.print(
            f"[red]Episode {episode_id} not found in module {resolved_id} "
            f"(or not currently discarded).[/red]"
        )
        raise SystemExit(1)


@app.command(name="purge")
async def lectures_purge(
    module_id: Annotated[
        str, cyclopts.Parameter(help="Module ID, course number (186.813), or name.")
    ],
    episode_id: Annotated[str, cyclopts.Parameter(help="Episode ID to purge indexed content for.")],
) -> None:
    """Remove indexed content (ChromaDB chunks, transcripts, knowledge index) for an episode."""
    from rich.console import Console

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.domain.errors import AuthError
    from sophia.infra.di import create_app
    from sophia.services.hermes_manage import purge_episode

    console = Console()

    try:
        async with create_app() as container:
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)
            from sophia.adapters.knowledge_store import ChromaKnowledgeStore

            store = ChromaKnowledgeStore(container.settings.data_dir / "knowledge")
            result = await purge_episode(
                container.db,
                store,
                resolved_id,
                episode_id,
            )
    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None

    total = (
        result.knowledge_chunks
        + result.transcript_segments
        + result.transcriptions
        + result.knowledge_index
    )
    if total == 0:
        console.print(
            f"[yellow]No indexed content found for episode {episode_id} "
            f"in module {module_id}.[/yellow]"
        )
    else:
        console.print(f"[green]Purged episode {episode_id}:[/green]")
        console.print(f"  ChromaDB chunks removed: {result.knowledge_chunks}")
        console.print(f"  Transcript segments removed: {result.transcript_segments}")
        console.print(f"  Transcription records removed: {result.transcriptions}")
        console.print(f"  Knowledge index records removed: {result.knowledge_index}")


@app.command(name="list")
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


@app.command(name="download")
async def lectures_download(
    module_id: Annotated[
        str,
        cyclopts.Parameter(
            help="Module ID, course number (186.813), or name."
        ),
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
    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.services.hermes_download import download_lectures

    console = Console()

    try:
        async with create_app() as container:
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)
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
                results = await download_lectures(container, resolved_id, on_progress=_on_progress)

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


@app.command(name="transcribe")
async def lectures_transcribe(
    module_id: Annotated[
        str,
        cyclopts.Parameter(
            help="Module ID, course number (186.813), or name."
        ),
    ],
) -> None:
    """Transcribe downloaded lectures using Whisper. Requires 'sophia lectures setup'."""
    from rich.console import Console
    from rich.table import Table

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.domain.errors import AuthError, TranscriptionError
    from sophia.infra.di import create_app
    from sophia.services.hermes_transcribe import transcribe_lectures

    console = Console()

    try:
        async with create_app() as container:
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)

            def _on_start(episode_id: str, title: str) -> None:
                console.print(f"[dim]Transcribing:[/dim] {title}...")

            def _on_complete(episode_id: str, segment_count: int) -> None:
                console.print(f"  [green]✓[/green] {segment_count} segments")

            results = await transcribe_lectures(
                container, resolved_id, on_start=_on_start, on_complete=_on_complete
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


@app.command(name="index")
async def lectures_index(
    module_id: Annotated[
        str,
        cyclopts.Parameter(
            help="Module ID, course number (186.813), or name."
        ),
    ],
) -> None:
    """Build search index from transcribed lectures. Requires transcription first."""
    from rich.console import Console
    from rich.table import Table

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.domain.errors import AuthError, EmbeddingError
    from sophia.infra.di import create_app
    from sophia.services.hermes_index import index_lectures

    console = Console()

    try:
        async with create_app() as container:
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)

            def _on_start(episode_id: str, title: str) -> None:
                console.print(f"[dim]Indexing:[/dim] {title}...")

            def _on_complete(episode_id: str, chunk_count: int) -> None:
                console.print(f"  [green]✓[/green] {chunk_count} chunks")

            results = await index_lectures(
                container, resolved_id, on_start=_on_start, on_complete=_on_complete
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


@app.command(name="process")
async def lectures_process(
    module_id: Annotated[
        str,
        cyclopts.Parameter(
            help="Module ID, course number (186.813), or name."
        ),
    ],
) -> None:
    """Run the full lecture pipeline: download → transcribe → index → extract topics."""
    from rich.console import Console
    from rich.table import Table

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.domain.errors import AuthError, EmbeddingError, TranscriptionError
    from sophia.infra.di import create_app
    from sophia.services.hermes_pipeline import PipelineResult, run_pipeline

    console = Console()
    _STATUS_STYLES = {"completed": "green", "skipped": "yellow", "failed": "red"}

    try:
        async with create_app() as container:
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)
            console.print(f"\n[bold]Pipeline for module {resolved_id}[/bold]\n")

            result: PipelineResult = await run_pipeline(container, resolved_id)

            # ── Summary table ─────────────────────────────────────────
            console.print("\n")
            table = Table(title="Pipeline Summary")
            table.add_column("Episode", style="cyan", no_wrap=False)
            table.add_column("Download", style="white")
            table.add_column("Transcribe", style="white")
            table.add_column("Index", style="white")

            # Build per-episode rows from downloads (source of episode IDs)
            transcribe_map = {r.episode_id: r for r in result.transcriptions}
            index_map = {r.episode_id: r for r in result.indexing}

            completed = {"download": 0, "transcribe": 0, "index": 0}
            skipped = {"download": 0, "transcribe": 0, "index": 0}
            failed = {"download": 0, "transcribe": 0, "index": 0}

            for dl in result.downloads:
                dl_style = _STATUS_STYLES.get(dl.status, "white")
                dl_cell = f"[{dl_style}]{dl.status}[/{dl_style}]"

                tr = transcribe_map.get(dl.episode_id)
                tr_status = tr.status if tr else "—"
                tr_style = _STATUS_STYLES.get(tr_status, "dim")
                tr_cell = f"[{tr_style}]{tr_status}[/{tr_style}]"

                ix = index_map.get(dl.episode_id)
                ix_status = ix.status if ix else "—"
                ix_style = _STATUS_STYLES.get(ix_status, "dim")
                ix_cell = f"[{ix_style}]{ix_status}[/{ix_style}]"

                table.add_row(dl.title, dl_cell, tr_cell, ix_cell)

                for stage, status in [
                    ("download", dl.status),
                    ("transcribe", tr_status),
                    ("index", ix_status),
                ]:
                    if status == "completed":
                        completed[stage] += 1
                    elif status == "skipped":
                        skipped[stage] += 1
                    elif status == "failed":
                        failed[stage] += 1

            # Totals row
            table.add_section()
            table.add_row(
                "[bold]Total[/bold]",
                f"[green]{completed['download']}[/green] / "
                f"[yellow]{skipped['download']}[/yellow] / "
                f"[red]{failed['download']}[/red]",
                f"[green]{completed['transcribe']}[/green] / "
                f"[yellow]{skipped['transcribe']}[/yellow] / "
                f"[red]{failed['transcribe']}[/red]",
                f"[green]{completed['index']}[/green] / "
                f"[yellow]{skipped['index']}[/yellow] / "
                f"[red]{failed['index']}[/red]",
            )

            console.print(table)

            if result.topics:
                console.print(f"\n[bold]Topics extracted:[/bold] {len(result.topics)}")
                for t in result.topics:
                    console.print(f"  • {t.topic}")

            console.print(
                '\n[dim]Next step:[/dim] [cyan]sophia lectures search "query" <module-id>[/cyan]'
            )

    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None
    except TranscriptionError as exc:
        console.print(f"[red]Transcription error:[/red] {exc}")
        raise SystemExit(1) from None
    except EmbeddingError as exc:
        console.print(f"[red]Embedding error:[/red] {exc}")
        raise SystemExit(1) from None


@app.command(name="search")
async def lectures_search(
    query: Annotated[str, cyclopts.Parameter(help="Natural language search query.")],
    module_id: Annotated[
        str, cyclopts.Parameter(help="Module ID, course number (186.813), or name.")
    ],
    *,
    count: Annotated[
        int, cyclopts.Parameter(help="Number of results.", name=["--count", "-n"])
    ] = 5,
) -> None:
    """Search lecture transcripts by semantic similarity."""
    from rich.console import Console
    from rich.panel import Panel

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.domain.errors import AuthError, EmbeddingError
    from sophia.infra.di import create_app
    from sophia.services.hermes_index import search_lectures

    console = Console()

    try:
        async with create_app() as container:
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)
            results = await search_lectures(container, resolved_id, query, n_results=count)

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
