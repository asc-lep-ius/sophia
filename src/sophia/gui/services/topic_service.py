"""GUI-safe wrappers for topic extraction and confidence rating data."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from sophia.services.athena_confidence import (
    get_confidence_ratings as _get_confidence_ratings,
)
from sophia.services.athena_confidence import (
    rate_confidence as _rate_confidence,
)
from sophia.services.athena_study import (
    extract_topics_from_lectures as _extract_topics,
)
from sophia.services.athena_study import (
    get_course_topics as _get_course_topics,
)

# Lazy import: athena_export requires optional 'athena' extra (genanki)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sophia.domain.models import ConfidenceRating, TopicMapping
    from sophia.infra.di import AppContainer

log = structlog.get_logger()


async def get_course_topics(app: AppContainer, *, course_id: int) -> list[TopicMapping]:
    """Fetch all extracted topics for a course."""
    try:
        return await _get_course_topics(app, course_id)
    except Exception:
        log.exception("get_course_topics_failed", course_id=course_id)
        return []


async def extract_topics(
    app: AppContainer,
    *,
    module_id: int,
    on_progress: Callable[[str], None] | None = None,
    force: bool = False,
) -> list[TopicMapping]:
    """Trigger topic extraction from lecture transcripts."""
    try:
        return await _extract_topics(app, module_id, on_progress=on_progress, force=force)
    except Exception:
        log.exception("extract_topics_failed", module_id=module_id)
        return []


async def get_topic_confidence(
    app: AppContainer,
    *,
    course_id: int,
    topic: str,
) -> ConfidenceRating | None:
    """Get the latest confidence rating for a specific topic."""
    try:
        ratings = await _get_confidence_ratings(app.db, course_id)
        return next((r for r in ratings if r.topic == topic), None)
    except Exception:
        log.exception("get_topic_confidence_failed", course_id=course_id, topic=topic)
        return None


async def save_confidence_prediction(
    app: AppContainer,
    *,
    topic: str,
    course_id: int,
    rating: int,
) -> ConfidenceRating | None:
    """Store a confidence prediction (1-5 scale) for a topic."""
    try:
        return await _rate_confidence(app, topic, course_id, rating)
    except Exception:
        log.exception("save_confidence_prediction_failed", topic=topic, course_id=course_id)
        return None


async def export_anki_deck(
    app: AppContainer,
    *,
    course_id: int,
    episode_id: str | None = None,
    interleaved: bool = True,
) -> bytes | None:
    """Export flashcards as Anki .apkg deck bytes.

    Returns the raw .apkg bytes for browser download, or None if no cards
    exist or an error occurs (including missing genanki dependency).
    """
    try:
        from sophia.services.athena_export import export_anki_deck as _export_anki_deck

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "deck.apkg"
            count = await _export_anki_deck(
                app.db,
                course_id,
                output_path,
                episode_id=episode_id,
                interleaved=interleaved,
            )
            if count == 0:
                return None
            return output_path.read_bytes()
    except Exception:
        log.exception("export_anki_deck_failed", course_id=course_id)
        return None
