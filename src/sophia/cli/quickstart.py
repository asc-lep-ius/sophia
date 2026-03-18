"""sophia quickstart — run the full study workflow in one command."""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import cyclopts

if TYPE_CHECKING:
    import aiosqlite
    from rich.console import Console

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
        async with create_app() as container:
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
                pipeline_done = await _is_pipeline_complete(container.db, resolved_id)

            if pipeline_done:
                console.print("[green]✓[/green] [1/5] Pipeline — already complete")
            else:
                console.print("[cyan]→[/cyan] [1/5] Running pipeline…")
                await _run_pipeline(container, resolved_id, console)

            # ── Step 2: Topics ────────────────────────────────────────────
            with console.status("[cyan][2/5] Checking topics…[/cyan]"):
                topics_done = await _has_topics(container.db, resolved_id)

            if topics_done:
                console.print("[green]✓[/green] [2/5] Topics — already extracted")
            else:
                console.print("[cyan]→[/cyan] [2/5] Extracting topics…")
                from sophia.services.athena_study import extract_topics_from_lectures

                try:
                    with Status("[cyan]Extracting topics…[/cyan]", console=console):
                        topics_list = await extract_topics_from_lectures(
                            container, resolved_id
                        )
                    console.print(
                        f"  [green]✓[/green] {len(topics_list)} topics extracted"
                    )
                except TopicExtractionError as exc:
                    console.print(f"  [yellow]Topic extraction failed:[/yellow] {exc}")
                    if not Confirm.ask(
                        "Continue without topics?", default=True, console=console
                    ):
                        return

            # ── Step 3: Confidence ────────────────────────────────────────
            with console.status("[cyan][3/5] Checking confidence ratings…[/cyan]"):
                confidence_done = await _has_confidence(container.db, resolved_id)

            if confidence_done:
                console.print("[green]✓[/green] [3/5] Confidence — already rated")
            else:
                console.print("[cyan]→[/cyan] [3/5] Rate your confidence…")
                await _run_confidence(container, resolved_id, console)

            # ── Step 4: Study session ─────────────────────────────────────
            with console.status("[cyan][4/5] Checking study sessions…[/cyan]"):
                session_done = await _has_completed_session(container.db, resolved_id)

            if session_done:
                console.print("[green]✓[/green] [4/5] Session — already completed")
            else:
                console.print("[cyan]→[/cyan] [4/5] Running study session…")
                await _run_session(container, resolved_id, console)

            # ── Step 5: Export ────────────────────────────────────────────
            console.print("[cyan]→[/cyan] [5/5] Exporting Anki deck…")
            out_path = Path(f"sophia-{resolved_id}.apkg")
            from sophia.services.athena_export import export_anki_deck

            count = await export_anki_deck(container.db, resolved_id, out_path)
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


async def _is_pipeline_complete(db: aiosqlite.Connection, module_id: int) -> bool:
    cursor = await db.execute(
        "SELECT"
        "  COUNT(*) AS total,"
        "  SUM(CASE WHEN ld.status  = 'completed' THEN 1 ELSE 0 END) AS dl,"
        "  SUM(CASE WHEN t.status   = 'completed' THEN 1 ELSE 0 END) AS tr,"
        "  SUM(CASE WHEN ki.status  = 'completed' THEN 1 ELSE 0 END) AS ix"
        " FROM lecture_downloads ld"
        " LEFT JOIN transcriptions  t  ON ld.episode_id = t.episode_id"
        " LEFT JOIN knowledge_index ki ON ld.episode_id = ki.episode_id"
        " WHERE ld.module_id = ?",
        (module_id,),
    )
    row = await cursor.fetchone()
    if not row or row[0] == 0:
        return False
    total, dl, tr, ix = row
    return bool(total and total == dl == tr == ix)


async def _has_topics(db: aiosqlite.Connection, module_id: int) -> bool:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM topic_mappings WHERE course_id = ?", (module_id,)
    )
    (count,) = await cursor.fetchone()
    return bool(count)


async def _has_confidence(db: aiosqlite.Connection, module_id: int) -> bool:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM confidence_ratings WHERE course_id = ?", (module_id,)
    )
    (count,) = await cursor.fetchone()
    return bool(count)


async def _has_completed_session(db: aiosqlite.Connection, module_id: int) -> bool:
    cursor = await db.execute(
        "SELECT COUNT(*) FROM study_sessions"
        " WHERE course_id = ? AND post_test_score IS NOT NULL",
        (module_id,),
    )
    (count,) = await cursor.fetchone()
    return bool(count)


# ── Step runners ───────────────────────────────────────────────────────────


async def _run_pipeline(
    container: AppContainer, resolved_id: int, console: Console
) -> None:
    """Run the Hermes pipeline with a simple status spinner."""
    from rich.status import Status

    from sophia.services.hermes_pipeline import run_pipeline

    with Status("[cyan]Processing lectures…[/cyan]", console=console):
        result = await run_pipeline(container, resolved_id)

    dl = sum(1 for r in result.downloads if r.status == "completed")
    tr = sum(1 for r in result.transcriptions if r.status == "completed")
    ix = sum(1 for r in result.indexing if r.status == "completed")
    console.print(
        f"  [green]✓[/green] {dl} downloaded · {tr} transcribed · {ix} indexed"
        f" · {len(result.topics)} topics"
    )


async def _run_confidence(
    container: AppContainer, resolved_id: int, console: Console
) -> None:
    """Prompt the user to rate confidence for all unrated topics."""
    from rich.prompt import IntPrompt

    from sophia.services.athena_confidence import rate_confidence
    from sophia.services.athena_study import get_course_topics

    topics = await get_course_topics(container, resolved_id)
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
        await rate_confidence(container, tm.topic, resolved_id, rating)

    console.print(f"  [green]✓[/green] {len(topics)} topics rated")


async def _run_session(
    container: AppContainer, resolved_id: int, console: Console
) -> None:
    """Run a single study session for the weakest topic."""
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.status import Status

    from sophia.domain.errors import StudySessionError, TopicExtractionError
    from sophia.services.athena_study import (
        complete_study_session,
        generate_study_questions,
        get_course_topics,
        get_lecture_context,
        save_flashcard,
        start_study_session,
    )

    topics = await get_course_topics(container, resolved_id)
    if not topics:
        console.print("  [yellow]No topics — skipping session.[/yellow]")
        return

    # Pick weakest based on confidence blind spots
    topic = topics[0].topic
    try:
        from sophia.services.athena_confidence import get_blind_spots

        blind_spots = await get_blind_spots(container.db, resolved_id)
        if blind_spots:
            topic = blind_spots[0].topic
    except Exception:
        pass

    console.print(f"  Topic: [bold]{topic}[/bold]")

    try:
        session = await start_study_session(container.db, resolved_id, topic)

        console.rule("[bold blue]Phase 1/4: Pre-Test[/bold blue]")
        with Status("Generating questions…", console=console):
            try:
                pre_qs = await generate_study_questions(container, resolved_id, topic, count=3)
            except TopicExtractionError:
                pre_qs = [f"Explain the concept of {topic} in your own words."] * 3

        pre_correct = 0
        for i, q in enumerate(pre_qs, 1):
            console.print(f"\n  [bold]Q{i}:[/bold] {q}")
            answer = Prompt.ask("  Your answer (or 'skip')", default="skip", console=console)
            if answer.strip().lower() != "skip" and Confirm.ask(
                "  Did you get it right?", default=False, console=console
            ):
                pre_correct += 1
        pre_score = pre_correct / len(pre_qs)
        console.print(f"\n  Pre-test: [bold]{pre_score:.0%}[/bold]")

        if not Confirm.ask("\nContinue to study phase?", default=True, console=console):
            await complete_study_session(container.db, session.id, pre_score, pre_score)
            return

        console.rule("[bold green]Phase 2/4: Study[/bold green]")
        with Status("Fetching lecture content…", console=console):
            lecture_text = await get_lecture_context(
                container, resolved_id, topic, with_provenance=True
            )
        if lecture_text:
            console.print(Panel(lecture_text[:2000], title=f"Lecture Notes: {topic}", expand=False))
        else:
            console.print("  [yellow]No lecture content found.[/yellow]")

        if not Confirm.ask("\nContinue to post-test?", default=True, console=console):
            await complete_study_session(container.db, session.id, pre_score, pre_score)
            return

        console.rule("[bold yellow]Phase 3/4: Post-Test[/bold yellow]")
        with Status("Generating questions…", console=console):
            try:
                post_qs = await generate_study_questions(container, resolved_id, topic, count=3)
            except TopicExtractionError:
                post_qs = pre_qs

        post_correct = 0
        for i, q in enumerate(post_qs, 1):
            console.print(f"\n  [bold]Q{i}:[/bold] {q}")
            answer = Prompt.ask("  Your answer (or 'skip')", default="skip", console=console)
            if answer.strip().lower() != "skip" and Confirm.ask(
                "  Did you get it right?", default=False, console=console
            ):
                post_correct += 1
        post_score = post_correct / len(post_qs)
        console.print(f"\n  Post-test: [bold]{post_score:.0%}[/bold]")

        await complete_study_session(container.db, session.id, pre_score, post_score)

        console.rule("[bold magenta]Phase 4/4: Flashcard[/bold magenta]")
        if Confirm.ask("\nCreate a flashcard for this topic?", default=True, console=console):
            front = Prompt.ask("  Front (question)", console=console)
            back = Prompt.ask("  Back (answer)", console=console)
            if front.strip() and back.strip():
                await save_flashcard(container.db, resolved_id, topic, front.strip(), back.strip())
                console.print("  [green]✓[/green] Flashcard saved")

    except StudySessionError as exc:
        console.print(f"  [red]Session error:[/red] {exc}")
