"""Athena study service — topic extraction, study sessions, and flashcards."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from sophia.adapters.topic_extractor import LLMTopicExtractor
from sophia.domain.errors import TopicExtractionError
from sophia.domain.models import (
    CardReviewAttempt,
    FlashcardSource,
    KnowledgeChunk,
    StudentFlashcard,
    StudySession,
    TopicMapping,
    TopicSource,
)
from sophia.services.hermes_setup import load_hermes_config

if TYPE_CHECKING:
    from collections.abc import Callable

    import aiosqlite

    from sophia.adapters.embedder import SentenceTransformerEmbedder
    from sophia.adapters.knowledge_store import ChromaKnowledgeStore
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

_MAX_TRANSCRIPT_CHARS = 12_000


def _create_topic_extractor(app: AppContainer) -> LLMTopicExtractor:
    config = load_hermes_config(app.settings.config_dir)
    if config is None:
        raise TopicExtractionError("Hermes not configured — run: sophia hermes setup")
    return LLMTopicExtractor(config.llm)


def _create_embedder(app: AppContainer) -> SentenceTransformerEmbedder:
    from sophia.adapters.embedder import SentenceTransformerEmbedder
    from sophia.domain.models import HermesConfig

    config = load_hermes_config(app.settings.config_dir)
    if config is None:
        config = HermesConfig()
    return SentenceTransformerEmbedder(config.embeddings)


def _create_store(app: AppContainer) -> ChromaKnowledgeStore:
    from sophia.adapters.knowledge_store import ChromaKnowledgeStore

    return ChromaKnowledgeStore(app.settings.data_dir / "knowledge")


async def _get_episode_ids(db: aiosqlite.Connection, module_id: int) -> list[str]:
    """Fetch episode IDs for a module to scope ChromaDB searches."""
    cursor = await db.execute(
        "SELECT episode_id FROM lecture_downloads WHERE module_id = ?",
        (module_id,),
    )
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def _get_series_title(db: aiosqlite.Connection, module_id: int) -> str:
    """Get the series title for a module to provide LLM context."""
    cursor = await db.execute(
        "SELECT series_id FROM lecture_downloads WHERE module_id = ? LIMIT 1",
        (module_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else ""


async def _get_transcript_text(db: aiosqlite.Connection, module_id: int) -> str:
    """Get representative transcript text from a module's indexed lectures."""
    cursor = await db.execute(
        "SELECT ts.text FROM transcript_segments ts "
        "JOIN transcriptions t ON ts.episode_id = t.episode_id "
        "WHERE t.module_id = ? AND t.status = 'completed' "
        "ORDER BY t.episode_id, ts.segment_index",
        (module_id,),
    )
    rows = await cursor.fetchall()
    if not rows:
        return ""

    # Concatenate segments until we hit the character budget
    parts: list[str] = []
    total = 0
    for (text,) in rows:
        if total + len(text) > _MAX_TRANSCRIPT_CHARS:
            break
        parts.append(text)
        total += len(text)

    return " ".join(parts)


async def extract_topics_from_lectures(
    app: AppContainer,
    module_id: int,
    *,
    on_progress: Callable[[str], None] | None = None,
) -> list[TopicMapping]:
    """Extract topics from indexed lecture transcripts for a module.

    1. Load transcript segments from DB for the module
    2. Concatenate representative text (budgeted to _MAX_TRANSCRIPT_CHARS)
    3. Call LLM TopicExtractor to get topic labels
    4. Persist to topic_mappings table
    5. Return the extracted topics
    """
    text = await _get_transcript_text(app.db, module_id)
    if not text:
        log.info("no_transcripts_for_topics", module_id=module_id)
        return []

    if on_progress:
        on_progress("Extracting topics from lecture transcripts…")

    extractor = _create_topic_extractor(app)

    # Use module_id as course_id (Moodle module context)
    course_id = module_id
    series_title = await _get_series_title(app.db, module_id)
    topic_labels = await extractor.extract_topics(text, course_context=series_title)

    if not topic_labels:
        log.info("no_topics_extracted", module_id=module_id)
        return []

    # Persist with upsert (idempotent)
    mappings: list[TopicMapping] = []
    for label in topic_labels:
        await app.db.execute(
            "INSERT INTO topic_mappings (topic, course_id, source, frequency) "
            "VALUES (?, ?, ?, 1) "
            "ON CONFLICT(topic, course_id, source) DO UPDATE SET "
            "frequency = frequency + 1",
            (label, course_id, TopicSource.LECTURE.value),
        )
        mappings.append(TopicMapping(topic=label, course_id=course_id, source=TopicSource.LECTURE))
    await app.db.commit()

    log.info("topics_extracted", module_id=module_id, count=len(mappings))
    return mappings


async def link_topics_to_lectures(
    app: AppContainer,
    course_id: int,
    module_id: int,
    topics: list[str],
    *,
    on_progress: Callable[[str, int], None] | None = None,
) -> dict[str, list[tuple[KnowledgeChunk, float]]]:
    """Cross-reference topics with lecture chunks via semantic search.

    For each topic:
    1. Embed the topic text
    2. Search the KnowledgeStore scoped to this module's episode_ids
    3. Store links in topic_lecture_links table
    4. Return mapping of topic -> [(chunk, score), ...]
    """
    if not topics:
        return {}

    episode_ids = await _get_episode_ids(app.db, module_id)
    if not episode_ids:
        log.info("no_episodes_for_linking", module_id=module_id)
        return {}

    embedder = _create_embedder(app)
    store = _create_store(app)

    results: dict[str, list[tuple[KnowledgeChunk, float]]] = {}

    for i, topic in enumerate(topics):
        if on_progress:
            on_progress(topic, i)

        query_embedding: list[float] = await asyncio.to_thread(embedder.embed_query, topic)
        search_results: list[tuple[KnowledgeChunk, float]] = await asyncio.to_thread(
            store.search, query_embedding, n_results=5, episode_ids=episode_ids
        )

        results[topic] = search_results

        # Persist links
        for chunk, score in search_results:
            await app.db.execute(
                "INSERT INTO topic_lecture_links "
                "(topic, course_id, chunk_id, episode_id, score) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(topic, course_id, chunk_id) DO UPDATE SET "
                "score = excluded.score",
                (topic, course_id, chunk.chunk_id, chunk.episode_id, score),
            )

    await app.db.commit()
    log.info("topics_linked", course_id=course_id, topic_count=len(results))
    return results


async def get_course_topics(
    app: AppContainer,
    course_id: int,
) -> list[TopicMapping]:
    """Load persisted topics for a course from the database."""
    cursor = await app.db.execute(
        "SELECT topic, course_id, source, frequency "
        "FROM topic_mappings WHERE course_id = ? "
        "ORDER BY frequency DESC, topic ASC",
        (course_id,),
    )
    rows = await cursor.fetchall()
    return [
        TopicMapping(
            topic=row[0],
            course_id=row[1],
            source=TopicSource(row[2]),
            frequency=row[3],
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Study sessions
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
# Question generation (RAG-grounded)
# ---------------------------------------------------------------------------

_FALLBACK_QUESTION = "Explain the concept of {topic} in your own words."


async def get_lecture_context(
    app: AppContainer,
    module_id: int,
    topic: str,
    *,
    n_results: int = 5,
) -> str:
    """Retrieve concatenated lecture transcript chunks relevant to a topic.

    Uses RAG: embed topic → search ChromaDB scoped to module's episodes.
    Returns empty string if no lecture data is available.
    """
    episode_ids = await _get_episode_ids(app.db, module_id)
    if not episode_ids:
        return ""

    embedder = _create_embedder(app)
    store = _create_store(app)
    query_embedding = await asyncio.to_thread(embedder.embed_query, topic)
    search_results = await asyncio.to_thread(
        store.search, query_embedding, n_results=n_results, episode_ids=episode_ids
    )
    return "\n\n".join(chunk.text for chunk, _score in search_results)


async def generate_study_questions(
    app: AppContainer,
    module_id: int,
    topic: str,
    count: int = 3,
) -> list[str]:
    """Generate practice questions for a topic, grounded in lecture content.

    Uses RAG: embed topic → search lecture chunks → feed to LLM as context.
    Falls back to generic questions if no lecture data or no LLM.
    """
    lecture_context = await get_lecture_context(app, module_id, topic)

    if not lecture_context:
        return [_FALLBACK_QUESTION.format(topic=topic)] * count

    extractor = _create_topic_extractor(app)
    questions: list[str] = []
    for _ in range(count):
        try:
            q = await extractor.generate_question(topic, lecture_context)
            if q and q not in questions:
                questions.append(q)
        except TopicExtractionError:
            log.warning("question_generation_failed", topic=topic)
            break

    while len(questions) < count:
        questions.append(_FALLBACK_QUESTION.format(topic=topic))

    return questions


# ---------------------------------------------------------------------------
# Flashcards
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


async def get_flashcards(
    db: aiosqlite.Connection,
    course_id: int,
    topic: str | None = None,
) -> list[StudentFlashcard]:
    """Load flashcards for a course, optionally filtered by topic."""
    if topic:
        cursor = await db.execute(
            "SELECT id, course_id, topic, front, back, source, created_at "
            "FROM student_flashcards WHERE course_id = ? AND topic = ? "
            "ORDER BY created_at DESC",
            (course_id, topic),
        )
    else:
        cursor = await db.execute(
            "SELECT id, course_id, topic, front, back, source, created_at "
            "FROM student_flashcards WHERE course_id = ? ORDER BY created_at DESC",
            (course_id,),
        )
    rows = await cursor.fetchall()
    return [
        StudentFlashcard(
            id=row[0],
            course_id=row[1],
            topic=row[2],
            front=row[3],
            back=row[4],
            source=FlashcardSource(row[5]),
            created_at=row[6] or "",
        )
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Card reviews
# ---------------------------------------------------------------------------


async def save_review_attempt(
    db: aiosqlite.Connection,
    flashcard_id: int,
    success: bool,
) -> CardReviewAttempt:
    """Insert a review attempt and return the model."""
    now = datetime.now(UTC).isoformat()
    cursor = await db.execute(
        "INSERT INTO card_review_attempts (flashcard_id, success, reviewed_at) VALUES (?, ?, ?)",
        (flashcard_id, success, now),
    )
    await db.commit()
    return CardReviewAttempt(
        id=cursor.lastrowid or 0,
        flashcard_id=flashcard_id,
        success=success,
        reviewed_at=now,
    )


async def get_review_stats(
    db: aiosqlite.Connection,
    course_id: int,
    topic: str | None = None,
) -> dict[str, Any]:
    """Get per-topic review stats: total_reviews, success_count, success_rate."""
    if topic:
        cursor = await db.execute(
            "SELECT COUNT(*), SUM(CASE WHEN cra.success THEN 1 ELSE 0 END) "
            "FROM card_review_attempts cra "
            "JOIN student_flashcards sf ON cra.flashcard_id = sf.id "
            "WHERE sf.course_id = ? AND sf.topic = ?",
            (course_id, topic),
        )
    else:
        cursor = await db.execute(
            "SELECT COUNT(*), SUM(CASE WHEN cra.success THEN 1 ELSE 0 END) "
            "FROM card_review_attempts cra "
            "JOIN student_flashcards sf ON cra.flashcard_id = sf.id "
            "WHERE sf.course_id = ?",
            (course_id,),
        )
    row = await cursor.fetchone()
    total = row[0] if row else 0
    success_count = int(row[1] or 0) if row else 0
    return {
        "total_reviews": total,
        "success_count": success_count,
        "success_rate": success_count / total if total > 0 else 0.0,
    }


async def get_due_cards(
    db: aiosqlite.Connection,
    course_id: int,
    topic: str | None = None,
    limit: int = 10,
) -> list[StudentFlashcard]:
    """Get cards due for review — never-reviewed first, then oldest reviewed."""
    base = (
        "SELECT sf.id, sf.course_id, sf.topic, sf.front, sf.back, sf.source, sf.created_at "
        "FROM student_flashcards sf "
        "LEFT JOIN card_review_attempts cra ON sf.id = cra.flashcard_id "
        "WHERE sf.course_id = ?"
    )
    params: list[int | str] = [course_id]
    if topic:
        base += " AND sf.topic = ?"
        params.append(topic)
    base += (
        " GROUP BY sf.id "
        "ORDER BY MAX(cra.reviewed_at) IS NOT NULL, MAX(cra.reviewed_at) ASC "
        "LIMIT ?"
    )
    params.append(limit)
    cursor = await db.execute(base, params)
    rows = await cursor.fetchall()
    return [
        StudentFlashcard(
            id=row[0],
            course_id=row[1],
            topic=row[2],
            front=row[3],
            back=row[4],
            source=FlashcardSource(row[5]),
            created_at=row[6] or "",
        )
        for row in rows
    ]


async def update_topic_calibration(
    db: aiosqlite.Connection,
    course_id: int,
    topic: str,
) -> None:
    """Compute review success rate and auto-populate confidence actual_score."""
    cursor = await db.execute(
        "SELECT COUNT(*), SUM(CASE WHEN cra.success THEN 1 ELSE 0 END) "
        "FROM card_review_attempts cra "
        "JOIN student_flashcards sf ON cra.flashcard_id = sf.id "
        "WHERE sf.course_id = ? AND sf.topic = ?",
        (course_id, topic),
    )
    row = await cursor.fetchone()
    if row is None or row[0] == 0:
        return

    success_count = int(row[1] or 0)
    success_rate = success_count / row[0]

    from sophia.services.athena_confidence import update_actual_score

    await update_actual_score(db, topic, course_id, success_rate)
    log.info(
        "topic_calibration_updated",
        topic=topic,
        course_id=course_id,
        success_rate=success_rate,
    )
