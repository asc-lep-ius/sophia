"""Athena — Study companion and topic analysis commands."""

from __future__ import annotations

from typing import Annotated

import cyclopts

app = cyclopts.App(
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


@app.command(name="topics")
async def study_topics(
    module_id: Annotated[
        str, cyclopts.Parameter(help="Module ID, course number (186.813), or name.")
    ],
) -> None:
    """Extract topics from lecture transcripts and cross-reference with lectures."""
    from rich.console import Console
    from rich.status import Status
    from rich.table import Table

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.domain.errors import AuthError, EmbeddingError, TopicExtractionError
    from sophia.infra.di import create_app
    from sophia.services.athena_study import (
        extract_topics_from_lectures,
        link_topics_to_lectures,
    )

    console = Console()

    try:
        async with create_app() as container:
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)
            with Status("Extracting topics from lectures…", console=console):
                topics = await extract_topics_from_lectures(container, resolved_id)

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
                    resolved_id,
                    resolved_id,
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
                (resolved_id,),
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


@app.command(name="confidence")
async def study_confidence(
    module_id: Annotated[
        str, cyclopts.Parameter(help="Module ID, course number (186.813), or name.")
    ],
) -> None:
    """Rate your confidence per topic — discover blind spots through calibration."""
    from rich.console import Console
    from rich.prompt import IntPrompt
    from rich.table import Table

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
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
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)
            topics = await get_course_topics(container, resolved_id)

            if not topics:
                console.print("[yellow]No topics found. Run 'sophia study topics' first.[/yellow]")
                return

            console.print(
                "[bold]Rate your confidence for each topic:[/bold]\n"
                "  [bold cyan]1[/bold cyan] Never heard of it        "
                "[bold cyan]2[/bold cyan] Vaguely familiar\n"
                "  [bold cyan]3[/bold cyan] Understand somewhat      "
                "[bold cyan]4[/bold cyan] Know it well\n"
                "  [bold cyan]5[/bold cyan] Could teach it\n"
            )

            for tm in topics:
                rating = IntPrompt.ask(
                    f"  {tm.topic}",
                    choices=["1", "2", "3", "4", "5"],
                    default=3,
                    console=console,
                )
                await rate_confidence(container, tm.topic, resolved_id, rating)

            console.print()

            all_ratings = await get_confidence_ratings(container.db, resolved_id)

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


@app.command(name="session")
async def study_session(
    module_id: Annotated[
        str, cyclopts.Parameter(help="Module ID, course number (186.813), or name.")
    ],
    topic: Annotated[
        str | None, cyclopts.Parameter(help="Topic to study. Defaults to weakest.")
    ] = None,
) -> None:
    """Guided study: pre-test → lecture review → post-test → flashcard creation."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.status import Status

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
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
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)
            # --- Load topics ---
            topics = await get_course_topics(container, resolved_id)

            if not topics:
                console.print("[yellow]No topics found. Run 'sophia study topics' first.[/yellow]")
                return

            # --- Select topic ---
            if topic is None:
                # Try to pick weakest blind spot, otherwise first topic
                try:
                    from sophia.services.athena_confidence import get_blind_spots

                    blind_spots = await get_blind_spots(container.db, resolved_id)
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
            session = await start_study_session(container.db, resolved_id, topic)

            # --- PRE-TEST ---
            console.rule("[bold blue]Phase 1/4: Pre-Test[/bold blue]")
            try:
                with Status("Generating pre-test questions…", console=console):
                    pre_questions = await generate_study_questions(
                        container, resolved_id, topic, count=3
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
            console.rule("[bold green]Phase 2/4: Study[/bold green]")
            with Status("Fetching lecture content…", console=console):
                from sophia.services.athena_study import get_lecture_context

                lecture_text = await get_lecture_context(container, resolved_id, topic)

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
            console.rule("[bold yellow]Phase 3/4: Post-Test[/bold yellow]")
            try:
                with Status("Generating post-test questions…", console=console):
                    post_questions = await generate_study_questions(
                        container, resolved_id, topic, count=3
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
            console.rule("[bold magenta]Phase 4/4: Flashcard[/bold magenta]")
            if Confirm.ask("\nCreate a flashcard for this topic?", default=True, console=console):
                front = Prompt.ask("  Front (question)", console=console)
                back = Prompt.ask("  Back (answer)", console=console)
                if front.strip() and back.strip():
                    await save_flashcard(
                        container.db, resolved_id, topic, front.strip(), back.strip()
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


@app.command(name="review")
async def study_review(
    module_id: Annotated[
        str, cyclopts.Parameter(help="Module ID, course number (186.813), or name.")
    ],
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

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
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
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)
            cards = await get_due_cards(container.db, resolved_id, topic=topic, limit=count)

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
                await update_topic_calibration(container.db, course_id=resolved_id, topic=t)

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
                stats = await get_review_stats(container.db, resolved_id, topic=t)
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


@app.command(name="explain")
async def study_explain(
    module_id: Annotated[
        str, cyclopts.Parameter(help="Module ID, course number (186.813), or name.")
    ],
    topic: Annotated[
        str | None, cyclopts.Parameter(help="Topic to filter. Defaults to all.")
    ] = None,
    count: Annotated[int, cyclopts.Parameter(help="Max cards to explain.")] = 5,
) -> None:
    """Self-explain wrong answers with fading scaffolds."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
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
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)
            cards = await get_failed_review_cards(
                container.db, resolved_id, topic=topic, limit=count,
            )

            if not cards:
                console.print(
                    "[yellow]No wrong answers to explain. "
                    "Review cards with 'sophia study review' first.[/yellow]"
                )
                return

            exp_count = await get_explanation_count(container.db, resolved_id)
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
                context = await get_lecture_context(container, resolved_id, card.topic)
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


@app.command(name="export")
async def study_export(
    module_id: Annotated[
        str, cyclopts.Parameter(help="Module ID, course number (186.813), or name.")
    ],
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

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.domain.errors import AthenaError
    from sophia.infra.di import create_app
    from sophia.services.athena_export import export_anki_deck

    console = Console()

    try:
        async with create_app() as container:
            async with handle_resolve_error():
                resolved_id = await resolve_module_id(module_id, container.moodle)
            out_path = Path(output or f"sophia-{resolved_id}.apkg")
            count = await export_anki_deck(
                container.db,
                resolved_id,
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


@app.command(name="due")
async def study_due(
    module_id: Annotated[
        str | None,
        cyclopts.Parameter(
            help="Module ID, course number (186.813), or name. Omit for all."
        ),
    ] = None,
) -> None:
    """Show topics due for spaced review and upcoming reviews."""
    from rich.console import Console
    from rich.table import Table

    from sophia.cli._resolver import handle_resolve_error, resolve_module_id
    from sophia.infra.di import create_app
    from sophia.services.athena_review import get_due_reviews, get_upcoming_reviews

    console = Console()

    async with create_app() as container:
        if module_id:
            async with handle_resolve_error():
                course_id = await resolve_module_id(module_id, container.moodle)
        else:
            course_id = None
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
