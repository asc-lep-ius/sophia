"""sophia quickstart — run the full study workflow in one command."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import cyclopts
import structlog
from sqlalchemy import case, func, select

from sophia.infra.schema import (
    confidence_ratings,
    knowledge_index,
    lecture_downloads,
    study_sessions,
    topic_mappings,
    transcriptions,
)

log = structlog.get_logger()

if TYPE_CHECKING:
    from rich.console import Console
    from sqlalchemy import Select
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.elements import Case, ColumnElement

    from sophia.infra.di import AppContainer

app = cyclopts.App(
    name="quickstart",
    help="Run the full workflow: process → topics → confidence → session → export.",
)


@app.command(name="__call__")
async def quickstart(
    module_id: Annotated[
        str, cyclopts.Parameter(help="Module ID, course number (186.813), or name.")
    ],
) -> None:
    """Chain the full study pipeline. Completed steps are automatically skipped."""
    from pathlib import Path

    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm
    from rich.status import Status

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.domain.errors import (
        AuthError,
        EmbeddingError,
        TopicExtractionError,
        TranscriptionError,
    )
    from sophia.infra.di import create_app

    console = Console()

    try:
        async with create_app() as container, container.session() as db:
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)

            console.print(
                Panel(
                    f"[bold]Sophia Quickstart: Module {resolved_id}[/bold]\n"
                    "process → topics → confidence → session → export\n"
                    "[dim]Completed steps are automatically skipped.[/dim]",
                    title="Quickstart",
                    style="cyan",
                    expand=False,
                )
            )

            # ── Step 1: Pipeline ──────────────────────────────────────────
            with console.status("[cyan][1/5] Checking pipeline status…[/cyan]"):
                pipeline_done = await _is_pipeline_complete(db, resolved_id)

            if pipeline_done:
                console.print("[green]✓[/green] [1/5] Pipeline — already complete")
            else:
                console.print("[cyan]→[/cyan] [1/5] Running pipeline…")
                await _run_pipeline(container, db, resolved_id, console)

            # ── Step 2: Topics ────────────────────────────────────────────
            with console.status("[cyan][2/5] Checking topics…[/cyan]"):
                topics_done = await _has_topics(db, resolved_id)

            if topics_done:
                console.print("[green]✓[/green] [2/5] Topics — already extracted")
            else:
                console.print("[cyan]→[/cyan] [2/5] Extracting topics…")
                from sophia.services.athena_study import extract_topics_from_lectures

                try:
                    with Status("[cyan]Extracting topics…[/cyan]", console=console):
                        topics_list = await extract_topics_from_lectures(
                            container,
                            db,
                            resolved_id,
                        )
                    console.print(f"  [green]✓[/green] {len(topics_list)} topics extracted")
                except TopicExtractionError as exc:
                    console.print(f"  [yellow]Topic extraction failed:[/yellow] {exc}")
                    if not Confirm.ask("Continue without topics?", default=True, console=console):
                        return

            # ── Step 3: Confidence ────────────────────────────────────────
            with console.status("[cyan][3/5] Checking confidence ratings…[/cyan]"):
                confidence_done = await _has_confidence(db, resolved_id)

            if confidence_done:
                console.print("[green]✓[/green] [3/5] Confidence — already rated")
            else:
                console.print("[cyan]→[/cyan] [3/5] Rate your confidence…")
                await _run_confidence(container, db, resolved_id, console)

            # ── Step 4: Study session ─────────────────────────────────────
            with console.status("[cyan][4/5] Checking study sessions…[/cyan]"):
                session_done = await _has_completed_session(db, resolved_id)

            if session_done:
                console.print("[green]✓[/green] [4/5] Session — already completed")
            else:
                console.print("[cyan]→[/cyan] [4/5] Running study session…")
                await _run_session(container, db, resolved_id, console)

            # ── Step 5: Export ────────────────────────────────────────────
            console.print("[cyan]→[/cyan] [5/5] Exporting Anki deck…")
            out_path = Path(f"sophia-{resolved_id}.apkg")
            from sophia.services.athena_export import export_anki_deck

            count = await export_anki_deck(db, resolved_id, out_path)
            if count:
                console.print(
                    f"  [green]✓[/green] Exported {count} cards → [cyan]{out_path}[/cyan]"
                )
            else:
                console.print("  [dim]No flashcards to export yet.[/dim]")

            console.print("\n[bold green]✅ Quickstart complete![/bold green]")

    except AuthError:
        console.print("[red]Not logged in — run:[/red] sophia auth login")
        raise SystemExit(1) from None
    except TranscriptionError as exc:
        console.print(f"[red]Transcription error:[/red] {exc}")
        raise SystemExit(1) from None
    except EmbeddingError as exc:
        console.print(f"[red]Embedding error:[/red] {exc}")
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        console.print("\n[dim]Quickstart interrupted.[/dim]")


# ── Completion checks ──────────────────────────────────────────────────────


def _completed(column: ColumnElement[str | None]) -> Case[int]:
    """1 when a pipeline stage reports completed, 0 otherwise."""
    return case((column == "completed", 1), else_=0)


async def _is_pipeline_complete(db: AsyncSession, module_id: int) -> bool:
    row = (
        await db.execute(
            select(
                func.count().label("total"),
                func.sum(_completed(lecture_downloads.c.status)).label("dl"),
                func.sum(_completed(transcriptions.c.status)).label("tr"),
                func.sum(_completed(knowledge_index.c.status)).label("ix"),
            )
            .select_from(lecture_downloads)
            .outerjoin(
                transcriptions,
                lecture_downloads.c.episode_id == transcriptions.c.episode_id,
            )
            .outerjoin(
                knowledge_index,
                lecture_downloads.c.episode_id == knowledge_index.c.episode_id,
            )
            .where(lecture_downloads.c.module_id == module_id)
        )
    ).one()
    if row.total == 0:
        return False
    return bool(row.total == row.dl == row.tr == row.ix)


async def _count_exists(db: AsyncSession, query: Select[tuple[int]]) -> bool:
    return bool(await db.scalar(query))


async def _has_topics(db: AsyncSession, module_id: int) -> bool:
    return await _count_exists(
        db,
        select(func.count())
        .select_from(topic_mappings)
        .where(topic_mappings.c.course_id == module_id),
    )


async def _has_confidence(db: AsyncSession, module_id: int) -> bool:
    return await _count_exists(
        db,
        select(func.count())
        .select_from(confidence_ratings)
        .where(confidence_ratings.c.course_id == module_id),
    )


async def _has_completed_session(db: AsyncSession, module_id: int) -> bool:
    return await _count_exists(
        db,
        select(func.count())
        .select_from(study_sessions)
        .where(
            study_sessions.c.course_id == module_id,
            study_sessions.c.post_test_score.is_not(None),
        ),
    )


# ── Step runners ───────────────────────────────────────────────────────────


async def _run_pipeline(
    container: AppContainer,
    db: AsyncSession,
    resolved_id: int,
    console: Console,
) -> None:
    """Run the Hermes pipeline with a simple status spinner."""
    from rich.status import Status

    from sophia.services.hermes_pipeline import run_pipeline

    with Status("[cyan]Processing lectures…[/cyan]", console=console):
        result = await run_pipeline(container, db, resolved_id)

    dl = sum(1 for r in result.downloads if r.status == "completed")
    tr = sum(1 for r in result.transcriptions if r.status == "completed")
    ix = sum(1 for r in result.indexing if r.status == "completed")
    console.print(
        f"  [green]✓[/green] {dl} downloaded · {tr} transcribed · {ix} indexed"
        f" · {len(result.topics)} topics"
    )


async def _run_confidence(
    container: AppContainer,
    db: AsyncSession,
    resolved_id: int,
    console: Console,
) -> None:
    """Prompt the user to rate confidence for all unrated topics."""
    from rich.prompt import IntPrompt

    from sophia.services.athena_confidence import rate_confidence
    from sophia.services.athena_study import get_course_topics

    topics = await get_course_topics(db, resolved_id)
    if not topics:
        console.print("  [yellow]No topics found — run study topics first.[/yellow]")
        return

    console.print(
        "  [dim]1[/dim] Never heard of it   "
        "[dim]2[/dim] Vaguely familiar   "
        "[dim]3[/dim] Understand somewhat\n"
        "  [dim]4[/dim] Know it well        "
        "[dim]5[/dim] Could teach it\n"
    )

    for tm in topics:
        rating = IntPrompt.ask(
            f"  {tm.topic}",
            choices=["1", "2", "3", "4", "5"],
            default=3,
            console=console,
        )
        await rate_confidence(db, tm.topic, resolved_id, rating)

    console.print(f"  [green]✓[/green] {len(topics)} topics rated")


async def _run_session(
    container: AppContainer,
    db: AsyncSession,
    resolved_id: int,
    console: Console,
) -> None:
    """Run a single study session for the weakest topic."""
    from sophia.domain.errors import StudySessionError
    from sophia.services.athena_session import run_interactive_session
    from sophia.services.athena_study import get_course_topics

    topics = await get_course_topics(db, resolved_id)
    if not topics:
        console.print("  [yellow]No topics — skipping session.[/yellow]")
        return

    # Pick weakest based on confidence blind spots
    topic = topics[0].topic
    try:
        from sophia.services.athena_confidence import get_blind_spots

        blind_spots = await get_blind_spots(db, resolved_id)
        if blind_spots:
            topic = blind_spots[0].topic
    except Exception:
        log.debug("blind_spot_lookup_failed", exc_info=True)

    console.print(f"  Topic: [bold]{topic}[/bold]")

    try:
        await run_interactive_session(container, db, resolved_id, topic, console)
    except StudySessionError as exc:
        console.print(f"  [red]Session error:[/red] {exc}")
