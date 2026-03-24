"""Athena session service — interactive study sessions and flashcard creation."""

from __future__ import annotations

from asyncio import sleep as asyncio_sleep
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sophia.domain.errors import TopicExtractionError
from sophia.domain.models import FlashcardSource, StudentFlashcard, StudySession
from sophia.services.athena_confidence import (
    get_blind_spots,
    get_confidence_ratings,
    get_topic_difficulty_level,
)
from sophia.services.athena_review import get_due_reviews

if TYPE_CHECKING:
    import aiosqlite
    from rich.console import Console

    from sophia.infra.di import AppContainer

_QUESTION_COUNT = 3
_FALLBACK_QUESTION = "Explain the concept of {topic} in your own words."


# ---------------------------------------------------------------------------
# Study sessions (CRUD)
# ---------------------------------------------------------------------------


async def start_study_session(
    db: aiosqlite.Connection,
    course_id: int,
    topic: str,
) -> StudySession:
    """Create a new study session."""
    now = datetime.now(UTC).isoformat()
    cursor = await db.execute(
        "INSERT INTO study_sessions (course_id, topic, started_at) VALUES (?, ?, ?)",
        (course_id, topic, now),
    )
    await db.commit()
    return StudySession(id=cursor.lastrowid or 0, course_id=course_id, topic=topic, started_at=now)


async def complete_study_session(
    db: aiosqlite.Connection,
    session_id: int,
    pre_test_score: float,
    post_test_score: float,
) -> None:
    """Record pre/post scores and mark session complete."""
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "UPDATE study_sessions SET pre_test_score = ?, post_test_score = ?, completed_at = ? "
        "WHERE id = ?",
        (pre_test_score, post_test_score, now, session_id),
    )
    await db.commit()


async def get_study_sessions(
    db: aiosqlite.Connection,
    course_id: int,
    topic: str | None = None,
) -> list[StudySession]:
    """Get study sessions, optionally filtered by topic."""
    if topic:
        cursor = await db.execute(
            "SELECT id, course_id, topic, pre_test_score, post_test_score, "
            "started_at, completed_at "
            "FROM study_sessions WHERE course_id = ? AND topic = ? ORDER BY started_at DESC",
            (course_id, topic),
        )
    else:
        cursor = await db.execute(
            "SELECT id, course_id, topic, pre_test_score, post_test_score, "
            "started_at, completed_at "
            "FROM study_sessions WHERE course_id = ? ORDER BY started_at DESC",
            (course_id,),
        )
    rows = await cursor.fetchall()
    return [
        StudySession(
            id=row[0],
            course_id=row[1],
            topic=row[2],
            pre_test_score=row[3],
            post_test_score=row[4],
            started_at=row[5] or "",
            completed_at=row[6],
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Flashcard creation
# ---------------------------------------------------------------------------


async def save_flashcard(
    db: aiosqlite.Connection,
    course_id: int,
    topic: str,
    front: str,
    back: str,
    source: str = "study",
) -> StudentFlashcard:
    """Save a student-authored flashcard."""
    now = datetime.now(UTC).isoformat()
    cursor = await db.execute(
        "INSERT INTO student_flashcards (course_id, topic, front, back, source, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (course_id, topic, front, back, source, now),
    )
    await db.commit()
    return StudentFlashcard(
        id=cursor.lastrowid or 0,
        course_id=course_id,
        topic=topic,
        front=front,
        back=back,
        source=FlashcardSource(source),
        created_at=now,
    )


# ---------------------------------------------------------------------------
# Interactive session (shared by quickstart + study session CLI)
# ---------------------------------------------------------------------------


def _run_quiz(questions: list[str], console: Console) -> int:
    """Ask a list of quiz questions interactively and return the correct count."""
    from rich.prompt import Confirm, Prompt

    correct = 0
    for i, q in enumerate(questions, 1):
        console.print(f"\n  [bold]Q{i}:[/bold] {q}")
        answer = Prompt.ask("  Your answer (or 'skip')", default="skip", console=console)
        if answer.strip().lower() == "skip":
            continue
        if Confirm.ask("  Did you get it right?", default=False, console=console):
            correct += 1
    return correct


def _run_quiz_no_skip(questions: list[str], console: Console) -> int:
    """Run quiz without skip option — generation effect."""
    from rich.prompt import Confirm, Prompt

    correct = 0
    for i, q in enumerate(questions, 1):
        console.print(f"\n  [bold]Q{i}:[/bold] {q}")
        console.print(
            "  [dim]Type your best guess — even a wrong attempt strengthens encoding.[/dim]"
        )
        answer = Prompt.ask("  Your answer", console=console)
        while not answer.strip():
            console.print(
                "  [yellow]Please type an answer — retrieval attempts strengthen learning.[/yellow]"
            )
            answer = Prompt.ask("  Your answer", console=console)
        if Confirm.ask("  Did you get it right?", default=False, console=console):
            correct += 1
    return correct


async def _run_pretest(
    app: AppContainer,
    course_id: int,
    topic: str,
    console: Console,
) -> tuple[float, list[str]]:
    """Phase 1: Generate and run pre-test questions (no-skip for generation effect)."""
    from rich.status import Status

    from sophia.services.athena_study import generate_study_questions

    console.rule("[bold blue]Phase 1/4: Pre-Test[/bold blue]")

    # Adaptive difficulty based on latest confidence
    ratings = await get_confidence_ratings(app.db, course_id)
    topic_rating = next((r for r in ratings if r.topic == topic), None)
    difficulty = get_topic_difficulty_level(topic_rating.predicted if topic_rating else None)

    with Status("Generating pre-test questions…", console=console):
        try:
            pre_qs = await generate_study_questions(
                app,
                course_id,
                topic,
                count=_QUESTION_COUNT,
                difficulty=difficulty.value,
            )
        except TopicExtractionError:
            pre_qs = [_FALLBACK_QUESTION.format(topic=topic)] * _QUESTION_COUNT

    pre_correct = _run_quiz_no_skip(pre_qs, console)
    pre_score = pre_correct / len(pre_qs) if pre_qs else 0.0
    console.print(f"\n  Pre-test score: [bold]{pre_score:.0%}[/bold] ({pre_correct}/{len(pre_qs)})")
    return pre_score, pre_qs


async def _run_study_phase(
    app: AppContainer,
    course_id: int,
    topic: str,
    console: Console,
) -> None:
    """Phase 2: Show lecture content for study."""
    from rich.panel import Panel
    from rich.status import Status

    from sophia.services.athena_study import get_lecture_context

    console.rule("[bold green]Phase 2/4: Study[/bold green]")
    with Status("Fetching lecture content…", console=console):
        lecture_text = await get_lecture_context(app, course_id, topic, with_provenance=True)

    if lecture_text:
        console.print(Panel(lecture_text[:2000], title=f"Lecture Notes: {topic}", expand=False))
    else:
        console.print("[yellow]No lecture content found for this topic.[/yellow]")


async def _run_posttest(
    app: AppContainer,
    course_id: int,
    topic: str,
    console: Console,
    pre_qs: list[str],
) -> float:
    """Phase 3: Generate and run post-test, show improvement."""
    from rich.status import Status

    from sophia.services.athena_study import generate_study_questions

    console.rule("[bold yellow]Phase 3/4: Post-Test[/bold yellow]")

    # Adaptive difficulty based on latest confidence
    ratings = await get_confidence_ratings(app.db, course_id)
    topic_rating = next((r for r in ratings if r.topic == topic), None)
    difficulty = get_topic_difficulty_level(topic_rating.predicted if topic_rating else None)

    with Status("Generating post-test questions…", console=console):
        try:
            post_qs = await generate_study_questions(
                app,
                course_id,
                topic,
                count=_QUESTION_COUNT,
                difficulty=difficulty.value,
            )
        except TopicExtractionError:
            post_qs = pre_qs

    post_correct = _run_quiz(post_qs, console)
    post_score = post_correct / len(post_qs) if post_qs else 0.0
    console.print(
        f"\n  Post-test score: [bold]{post_score:.0%}[/bold] ({post_correct}/{len(post_qs)})"
    )
    return post_score


async def _run_flashcard_phase(
    db: aiosqlite.Connection,
    course_id: int,
    topic: str,
    console: Console,
) -> None:
    """Phase 4: Optionally create a flashcard."""
    from rich.prompt import Confirm, Prompt

    console.rule("[bold magenta]Phase 4/4: Flashcard[/bold magenta]")
    if Confirm.ask("\nCreate a flashcard for this topic?", default=True, console=console):
        front = Prompt.ask("  Front (question)", console=console)
        back = Prompt.ask("  Back (answer)", console=console)
        if front.strip() and back.strip():
            await save_flashcard(db, course_id, topic, front.strip(), back.strip())
            console.print("  [green]✓[/green] Flashcard saved")
        else:
            console.print("[dim]Skipped — empty flashcard.[/dim]")


async def _run_reflection(console: Console, delay_seconds: int) -> None:
    """Show reflection prompt and countdown before revealing results."""
    if delay_seconds <= 0:
        return
    console.print("\n[bold cyan]Before seeing your results, take a moment to reflect:[/bold cyan]")
    console.print("  - Which questions felt hardest?")
    console.print("  - Where were you most uncertain?")
    console.print("  - What concepts do you want to review?\n")

    from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn

    with Progress(
        TextColumn("[bold blue]Reflecting..."),
        BarColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("reflect", total=delay_seconds)
        for _ in range(delay_seconds):
            await asyncio_sleep(1)
            progress.advance(task, 1)


async def run_interactive_session(
    app: AppContainer,
    course_id: int,
    topic: str,
    console: Console,
    *,
    feedback_delay: int = 30,
) -> None:
    """Run the 4-phase interactive study loop: pre-test → study → post-test → flashcard.

    Raises ``StudySessionError`` on DB failures — callers handle presentation.
    """
    from rich.prompt import Confirm

    session = await start_study_session(app.db, course_id, topic)

    pre_score, pre_qs = await _run_pretest(app, course_id, topic, console)

    if not Confirm.ask("\nContinue to study phase?", default=True, console=console):
        await complete_study_session(app.db, session.id, pre_score, pre_score)
        console.print("[dim]Session saved with pre-test only.[/dim]")
        return

    await _run_study_phase(app, course_id, topic, console)

    if not Confirm.ask("\nContinue to post-test?", default=True, console=console):
        await complete_study_session(app.db, session.id, pre_score, pre_score)
        console.print("[dim]Session saved with pre-test only.[/dim]")
        return

    post_score = await _run_posttest(app, course_id, topic, console, pre_qs)

    await _run_reflection(console, feedback_delay)

    improvement = post_score - pre_score
    if improvement > 0:
        console.print(f"\n  [green]📈 Improvement: +{improvement:.0%}[/green]")
    elif improvement < 0:
        console.print(f"\n  [yellow]📉 Change: {improvement:.0%}[/yellow]")
    else:
        console.print("\n  [dim]➡ No change in score.[/dim]")

    await complete_study_session(app.db, session.id, pre_score, post_score)

    await _run_flashcard_phase(app.db, course_id, topic, console)

    console.print(
        "\n[dim]💡 Tip: Try --interleave to mix topics"
        " — interleaving strengthens long-term retention.[/dim]"
    )


# ---------------------------------------------------------------------------
# Interleaved review mode
# ---------------------------------------------------------------------------


async def _get_missed_lecture_topics(db: aiosqlite.Connection, course_id: int) -> list[str]:
    """Get topics only covered in missed lectures for a course (zero-exposure gaps)."""
    cursor = await db.execute(
        "SELECT DISTINCT tll.topic "
        "FROM topic_lecture_links tll "
        "JOIN lecture_downloads ld ON ld.episode_id = tll.episode_id "
        "WHERE tll.course_id = ? AND ld.missed_at IS NOT NULL",
        (course_id,),
    )
    missed = {row[0] for row in await cursor.fetchall()}

    cursor = await db.execute(
        "SELECT DISTINCT tll.topic "
        "FROM topic_lecture_links tll "
        "JOIN lecture_downloads ld ON ld.episode_id = tll.episode_id "
        "WHERE tll.course_id = ? AND ld.missed_at IS NULL",
        (course_id,),
    )
    attended = {row[0] for row in await cursor.fetchall()}

    return sorted(missed - attended)


async def _select_interleave_topics(
    app: AppContainer,
    course_id: int,
    *,
    max_topics: int = 3,
) -> list[str]:
    """Select 2-3 topics for interleaved review, weighted by blind-spot severity."""
    db = app.db

    # 1. Blind spots (overconfident topics) get priority
    blind_spots = await get_blind_spots(db, course_id)
    topics = [r.topic for r in blind_spots]

    # 2. Missed-lecture topics — zero-exposure gaps
    if len(topics) < max_topics:
        missed_topics = await _get_missed_lecture_topics(db, course_id)
        for t in missed_topics:
            if t not in topics:
                topics.append(t)
            if len(topics) >= max_topics:
                break

    # 3. Due reviews
    if len(topics) < max_topics:
        due = await get_due_reviews(db, course_id)
        for r in due:
            if r.topic not in topics:
                topics.append(r.topic)
            if len(topics) >= max_topics:
                break

    # 4. All course topics
    if len(topics) < 2:
        from sophia.services.athena_study import get_course_topics

        all_topics = await get_course_topics(app, course_id)
        for tm in all_topics:
            if tm.topic not in topics:
                topics.append(tm.topic)
            if len(topics) >= max_topics:
                break

    return topics[:max_topics]


async def run_interleaved_session(
    app: AppContainer,
    course_id: int,
    *,
    console: Console | None = None,
    feedback_delay: int = 30,
) -> None:
    """Run study session interleaving multiple topics."""
    if console is None:
        from rich.console import Console as RichConsole

        console = RichConsole()

    from sophia.services.athena_study import generate_study_questions, get_lecture_context

    topics = await _select_interleave_topics(app, course_id)
    if len(topics) < 2:
        console.print(
            "[yellow]Not enough topics for interleaving, running single-topic session.[/yellow]"
        )
        single_topic = topics[0] if topics else "General"
        await run_interactive_session(
            app,
            course_id,
            single_topic,
            console,
            feedback_delay=feedback_delay,
        )
        return

    console.print(f"\n[bold]Interleaved session with {len(topics)} topics:[/bold]")
    for t in topics:
        console.print(f"  • {t}")

    # Track per-topic sessions
    sessions: dict[str, int] = {}
    for t in topics:
        session = await start_study_session(app.db, course_id, t)
        sessions[t] = session.id

    # Pre-test: round-robin 1 question per topic
    console.rule("[bold blue]Phase 1/4: Pre-Test (interleaved)[/bold blue]")
    pre_qs: dict[str, list[str]] = {}
    pre_scores: dict[str, float] = {}
    all_pre_qs: list[str] = []
    ratings = await get_confidence_ratings(app.db, course_id)
    for t in topics:
        topic_rating = next((r for r in ratings if r.topic == t), None)
        difficulty = get_topic_difficulty_level(topic_rating.predicted if topic_rating else None)
        try:
            qs = await generate_study_questions(
                app, course_id, t, count=1, difficulty=difficulty.value
            )
        except TopicExtractionError:
            qs = [_FALLBACK_QUESTION.format(topic=t)]
        pre_qs[t] = qs
        all_pre_qs.extend(qs)

    pre_correct = _run_quiz_no_skip(all_pre_qs, console)
    pre_total = len(all_pre_qs)
    pre_score_overall = pre_correct / pre_total if pre_total else 0.0
    for t in topics:
        pre_scores[t] = pre_score_overall
    console.print(
        f"\n  Pre-test score: [bold]{pre_score_overall:.0%}[/bold] ({pre_correct}/{pre_total})"
    )

    # Study phase: lecture context per topic
    console.rule("[bold green]Phase 2/4: Study (interleaved)[/bold green]")
    for t in topics:
        lecture_text = await get_lecture_context(app, course_id, t, with_provenance=True)
        if lecture_text:
            from rich.panel import Panel

            console.print(Panel(lecture_text[:2000], title=f"Lecture Notes: {t}", expand=False))
        else:
            console.print(f"[yellow]No lecture content for {t}.[/yellow]")

    # Post-test: round-robin 1 question per topic (interleaved order)
    console.rule("[bold yellow]Phase 3/4: Post-Test (interleaved)[/bold yellow]")
    all_post_qs: list[str] = []
    for t in topics:
        topic_rating = next((r for r in ratings if r.topic == t), None)
        difficulty = get_topic_difficulty_level(topic_rating.predicted if topic_rating else None)
        try:
            qs = await generate_study_questions(
                app, course_id, t, count=1, difficulty=difficulty.value
            )
        except TopicExtractionError:
            qs = pre_qs.get(t, [_FALLBACK_QUESTION.format(topic=t)])
        all_post_qs.extend(qs)

    post_correct = _run_quiz(all_post_qs, console)
    post_total = len(all_post_qs)
    post_score_overall = post_correct / post_total if post_total else 0.0
    console.print(
        f"\n  Post-test score: [bold]{post_score_overall:.0%}[/bold] ({post_correct}/{post_total})"
    )

    await _run_reflection(console, feedback_delay)

    # Results
    improvement = post_score_overall - pre_score_overall
    if improvement > 0:
        console.print(f"\n  [green]📈 Improvement: +{improvement:.0%}[/green]")
    elif improvement < 0:
        console.print(f"\n  [yellow]📉 Change: {improvement:.0%}[/yellow]")
    else:
        console.print("\n  [dim]➡ No change in score.[/dim]")

    # Complete all sessions
    for t in topics:
        await complete_study_session(
            app.db,
            sessions[t],
            pre_scores[t],
            post_score_overall,
        )

    # Flashcard: one per topic
    for t in topics:
        await _run_flashcard_phase(app.db, course_id, t, console)
