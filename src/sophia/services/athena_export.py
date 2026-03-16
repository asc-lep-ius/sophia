"""Athena export service — Anki deck generation from student flashcards."""

from __future__ import annotations

import hashlib
import random
from typing import TYPE_CHECKING

from sophia.domain.errors import AthenaError
from sophia.services.athena_study import get_flashcards

if TYPE_CHECKING:
    from pathlib import Path

    import aiosqlite


async def export_anki_deck(
    db: aiosqlite.Connection,
    course_id: int,
    output_path: Path,
    *,
    interleaved: bool = True,
    deck_name: str | None = None,
) -> int:
    """Export flashcards as an Anki .apkg deck.

    Returns the number of cards exported.
    Raises AthenaError if genanki is not installed.
    """
    try:
        import genanki
    except ImportError as e:
        raise AthenaError(
            "Anki export requires the 'athena' extra: uv pip install sophia[athena]"
        ) from e

    cards = await get_flashcards(db, course_id)
    if not cards:
        return 0

    model_id = int(hashlib.sha256(f"sophia-model-{course_id}".encode()).hexdigest()[:8], 16) & 0x7FFFFFFF
    deck_id = int(hashlib.sha256(f"sophia-deck-{course_id}".encode()).hexdigest()[:8], 16) & 0x7FFFFFFF

    model = genanki.Model(
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
    deck = genanki.Deck(deck_id, name)

    notes = []
    for card in cards:
        tag_topic = card.topic.replace(" ", "_")
        note = genanki.Note(
            model=model,
            fields=[card.front, card.back, card.topic, card.source.value, card.created_at],
            tags=[tag_topic, card.source.value],
        )
        notes.append(note)

    if interleaved:
        random.Random(course_id).shuffle(notes)
    else:
        notes.sort(key=lambda n: n.fields[2])  # fields[2] = Topic

    for note in notes:
        deck.add_note(note)

    package = genanki.Package(deck)
    package.write_to_file(str(output_path))

    return len(notes)
