"""GUI-safe wrappers for athena study-session data fetching.

These extract the pure data-fetching logic from the CLI-entangled
``athena_session`` functions so GUI pages can call them without
Rich Console dependencies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from sophia.domain.errors import TopicExtractionError
from sophia.services.athena_confidence import (
    get_blind_spots,
    get_confidence_ratings,
    get_topic_difficulty_level,
    rating_to_score,
    update_actual_score,
)
from sophia.services.athena_review import get_due_reviews
from sophia.services.athena_session import (
    complete_study_session,
    get_study_sessions,
    save_flashcard,
    start_study_session,
)
from sophia.services.athena_study import (
    generate_study_questions,
    get_course_topics,
    get_lecture_context,
    update_topic_calibration,
)

if TYPE_CHECKING:
    import aiosqlite

    from sophia.domain.models import DifficultyLevel, StudentFlashcard, StudySession
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


# ---------------------------------------------------------------------------
# Interleaving & session management (Phase 5A)
# ---------------------------------------------------------------------------

# Baseline confidence: rating_to_score(1) = 0.0 on a 1-5 scale
_NOVEL_CONFIDENCE_THRESHOLD = rating_to_score(1)


async def _get_missed_lecture_topics(
    db: aiosqlite.Connection,
    course_id: int,
) -> list[str]:
    """Topics only covered in missed lectures (zero-exposure gaps)."""
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


async def select_interleave_topics(
    app: AppContainer,
    course_id: int,
    *,
    max_topics: int = 3,
) -> list[str]:
    """Select topics for interleaved review.

    Priority: blind spots → missed-lecture → due reviews → all course topics.
    """
    db = app.db
    topics: list[str] = []

    # 1. Blind spots (overconfident topics)
    blind_spots = await get_blind_spots(db, course_id)
    topics.extend(r.topic for r in blind_spots)

    # 2. Missed-lecture topics
    if len(topics) < max_topics:
        missed = await _get_missed_lecture_topics(db, course_id)
        for t in missed:
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

    # 4. All course topics (fill when < 2 selected)
    if len(topics) < 2:
        all_topics = await get_course_topics(app, course_id)
        for tm in all_topics:
            if tm.topic not in topics:
                topics.append(tm.topic)
            if len(topics) >= max_topics:
                break

    return topics[:max_topics]


async def check_novel_topic(
    app: AppContainer,
    course_id: int,
    topic: str,
) -> bool:
    """Return True if student has zero prior sessions AND no confidence > baseline."""
    sessions = await get_study_sessions(app.db, course_id, topic)
    if sessions:
        return False
    ratings = await get_confidence_ratings(app.db, course_id)
    topic_rating = next((r for r in ratings if r.topic == topic), None)
    return not (topic_rating and topic_rating.predicted > _NOVEL_CONFIDENCE_THRESHOLD)


async def start_session(
    app: AppContainer,
    course_id: int,
    topic: str,
) -> StudySession:
    """Start a new study session."""
    return await start_study_session(app.db, course_id, topic)


async def complete_session(
    app: AppContainer,
    *,
    session_id: int,
    pre_score: float,
    post_score: float,
) -> None:
    """Record pre/post scores and mark session complete."""
    await complete_study_session(app.db, session_id, pre_score, post_score)


async def save_study_flashcard(
    app: AppContainer,
    course_id: int,
    topic: str,
    front: str,
    back: str,
) -> StudentFlashcard:
    """Save a student-authored flashcard from a study session."""
    return await save_flashcard(app.db, course_id, topic, front, back)


async def finalize_calibration(
    app: AppContainer,
    course_id: int,
    topic: str,
    actual_score: float,
) -> None:
    """Update actual score and recalculate topic calibration."""
    await update_actual_score(app.db, topic, course_id, actual_score)
    await update_topic_calibration(app.db, course_id, topic)


def compute_score(answers: dict[str, str], questions: list[str]) -> float:
    """Compute a rough score (fraction of non-empty answers). Range 0.0–1.0."""
    if not questions:
        return 0.0
    return sum(1 for a in answers.values() if a.strip()) / len(questions)


def format_improvement(pre: float, post: float) -> str:
    """Format pre→post delta, e.g. '40% → 80% (+40%)'."""
    delta = (post - pre) * 100
    return f"{pre * 100:.0f}% \u2192 {post * 100:.0f}% ({delta:+.0f}%)"
