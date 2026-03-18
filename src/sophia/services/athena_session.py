"""Athena session service — interactive study sessions and flashcard creation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sophia.domain.errors import TopicExtractionError
from sophia.domain.models import FlashcardSource, StudentFlashcard, StudySession

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


async def _run_pretest(
    app: AppContainer,
    course_id: int,
    topic: str,
    console: Console,
) -> tuple[float, list[str]]:
    """Phase 1: Generate and run pre-test questions."""
    from rich.status import Status

    from sophia.services.athena_study import generate_study_questions

    console.rule("[bold blue]Phase 1/4: Pre-Test[/bold blue]")
    with Status("Generating pre-test questions…", console=console):
        try:
            pre_qs = await generate_study_questions(app, course_id, topic, count=_QUESTION_COUNT)
        except TopicExtractionError:
            pre_qs = [_FALLBACK_QUESTION.format(topic=topic)] * _QUESTION_COUNT

    pre_correct = _run_quiz(pre_qs, console)
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
    pre_score: float,
) -> float:
    """Phase 3: Generate and run post-test, show improvement."""
    from rich.status import Status

    from sophia.services.athena_study import generate_study_questions

    console.rule("[bold yellow]Phase 3/4: Post-Test[/bold yellow]")
    with Status("Generating post-test questions…", console=console):
        try:
            post_qs = await generate_study_questions(app, course_id, topic, count=_QUESTION_COUNT)
        except TopicExtractionError:
            post_qs = pre_qs

    post_correct = _run_quiz(post_qs, console)
    post_score = post_correct / len(post_qs) if post_qs else 0.0
    console.print(
        f"\n  Post-test score: [bold]{post_score:.0%}[/bold] ({post_correct}/{len(post_qs)})"
    )

    improvement = post_score - pre_score
    if improvement > 0:
        console.print(f"\n  [green]📈 Improvement: +{improvement:.0%}[/green]")
    elif improvement < 0:
        console.print(f"\n  [yellow]📉 Change: {improvement:.0%}[/yellow]")
    else:
        console.print("\n  [dim]➡ No change in score.[/dim]")

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


async def run_interactive_session(
    app: AppContainer,
    course_id: int,
    topic: str,
    console: Console,
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

    post_score = await _run_posttest(app, course_id, topic, console, pre_qs, pre_score)

    await complete_study_session(app.db, session.id, pre_score, post_score)

    await _run_flashcard_phase(app.db, course_id, topic, console)
