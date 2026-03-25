"""GUI-safe wrappers for athena study-session data fetching.

These extract the pure data-fetching logic from the CLI-entangled
``athena_session`` functions so GUI pages can call them without
Rich Console dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from sophia.domain.errors import TopicExtractionError
from sophia.services.athena_confidence import get_confidence_ratings, get_topic_difficulty_level
from sophia.services.athena_study import generate_study_questions, get_lecture_context

if TYPE_CHECKING:
    from sophia.domain.models import DifficultyLevel
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

_FALLBACK_QUESTION = "Explain the concept of {topic} in your own words."


async def _determine_difficulty(app: AppContainer, course_id: int, topic: str) -> DifficultyLevel:
    """Look up the latest confidence rating for *topic* and map to difficulty."""
    ratings = await get_confidence_ratings(app.db, course_id)
    topic_rating = next((r for r in ratings if r.topic == topic), None)
    return get_topic_difficulty_level(topic_rating.predicted if topic_rating else None)


async def get_pretest_questions(
    app: AppContainer,
    course_id: int,
    topic: str,
    *,
    count: int = 3,
) -> tuple[list[str], DifficultyLevel]:
    """Generate pre-test questions for a topic, handling extraction failures.

    Returns ``(questions, difficulty_level)``.
    """
    difficulty = await _determine_difficulty(app, course_id, topic)
    try:
        questions = await generate_study_questions(
            app, course_id, topic, count=count, difficulty=difficulty.value
        )
    except TopicExtractionError:
        log.warning("pretest_generation_failed", topic=topic, course_id=course_id)
        questions = [_FALLBACK_QUESTION.format(topic=topic)] * count
    return questions, difficulty


async def get_study_material(
    app: AppContainer,
    course_id: int,
    topic: str,
) -> str:
    """Fetch lecture content with provenance annotations."""
    return await get_lecture_context(app, course_id, topic, with_provenance=True)


async def get_posttest_questions(
    app: AppContainer,
    course_id: int,
    topic: str,
    *,
    count: int = 3,
) -> tuple[list[str], DifficultyLevel]:
    """Generate post-test questions, re-determining difficulty from fresh ratings.

    Returns ``(questions, difficulty_level)``.
    """
    difficulty = await _determine_difficulty(app, course_id, topic)
    try:
        questions = await generate_study_questions(
            app, course_id, topic, count=count, difficulty=difficulty.value
        )
    except TopicExtractionError:
        log.warning("posttest_generation_failed", topic=topic, course_id=course_id)
        questions = [_FALLBACK_QUESTION.format(topic=topic)] * count
    return questions, difficulty
