"""Athena export service — Anki deck generation from student flashcards."""

from __future__ import annotations

import hashlib
import random
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from sophia.domain.errors import AthenaError
from sophia.domain.models import FlashcardSource, StudentFlashcard
from sophia.infra.schema import student_flashcards, topic_lecture_links
from sophia.services.athena_study import get_flashcards

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession


async def _get_flashcards_for_episode(
    session: AsyncSession,
    course_id: int,
    episode_id: str,
) -> list[StudentFlashcard]:
    """Load flashcards whose topics are linked to *episode_id*."""
    rows = (
        await session.execute(
            select(student_flashcards)
            .join(
                topic_lecture_links,
                (student_flashcards.c.topic == topic_lecture_links.c.topic)
                & (student_flashcards.c.course_id == topic_lecture_links.c.course_id),
            )
            .where(
                topic_lecture_links.c.episode_id == episode_id,
                student_flashcards.c.course_id == course_id,
            )
            .distinct()
            .order_by(student_flashcards.c.created_at.desc())
        )
    ).all()
    return [
        StudentFlashcard(
            id=row.id,
            course_id=row.course_id,
            topic=row.topic,
            front=row.front,
            back=row.back,
            source=FlashcardSource(row.source),
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        for row in rows
    ]


async def export_anki_deck(
    session: AsyncSession,
    course_id: int,
    output_path: Path,
    *,
    episode_id: str | None = None,
    interleaved: bool = True,
    deck_name: str | None = None,
) -> int:
    """Export flashcards as an Anki .apkg deck.

    When *episode_id* is given, only flashcards whose topics are linked
    to that lecture episode (via ``topic_lecture_links``) are included.

    Returns the number of cards exported.
    Raises AthenaError if genanki is not installed.
    """
    try:
        import genanki  # pyright: ignore[reportMissingImports, reportMissingTypeStubs]
    except ImportError as e:
        raise AthenaError(
            "Anki export requires the 'athena' extra: uv pip install sophia[athena]"
        ) from e

    if episode_id is not None:
        cards = await _get_flashcards_for_episode(session, course_id, episode_id)
    else:
        cards = await get_flashcards(session, course_id)
    if not cards:
        return 0

    def _stable_id(label: str) -> int:
        digest = hashlib.sha256(f"sophia-{label}-{course_id}".encode()).hexdigest()
        return int(digest[:8], 16) & 0x7FFFFFFF

    model_id = _stable_id("model")
    deck_id = _stable_id("deck")

    model: Any = genanki.Model(  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
        model_id,
        "Sophia Flashcard",
        fields=[
            {"name": "Front"},
            {"name": "Back"},
            {"name": "Topic"},
            {"name": "Source"},
            {"name": "Created"},
        ],
        templates=[
            {
                "name": "Card 1",
                "qfmt": "{{Front}}",
                "afmt": '{{FrontSide}}<hr id="answer">{{Back}}',
            }
        ],
    )

    name = deck_name or f"Sophia — Course {course_id}"
    deck: Any = genanki.Deck(deck_id, name)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]

    notes: list[Any] = []
    for card in cards:
        tag_topic = card.topic.replace(" ", "_")
        note: Any = genanki.Note(  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
            model=model,
            fields=[card.front, card.back, card.topic, card.source.value, card.created_at],
            tags=[tag_topic, card.source.value],
        )
        notes.append(note)

    if interleaved:
        random.Random(course_id).shuffle(notes)
    else:
        notes.sort(key=lambda n: n.fields[2])  # pyright: ignore[reportUnknownLambdaType, reportUnknownMemberType]

    for note in notes:
        deck.add_note(note)  # pyright: ignore[reportUnknownMemberType]

    package: Any = genanki.Package(deck)  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    package.write_to_file(str(output_path))  # pyright: ignore[reportUnknownMemberType]

    return len(notes)
