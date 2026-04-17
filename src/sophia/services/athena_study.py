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
    SelfExplanation,
    StudentFlashcard,
    TopicMapping,
    TopicSource,
)
from sophia.services.athena_session import (
    complete_study_session as complete_study_session,
)
from sophia.services.athena_session import (
    get_study_sessions as get_study_sessions,
)
from sophia.services.athena_session import (
    run_interactive_session as run_interactive_session,
)
from sophia.services.athena_session import (
    save_flashcard as save_flashcard,
)
from sophia.services.athena_session import (
    start_study_session as start_study_session,
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


# Module-level caches — one instance per CLI session, not per function call.
# The ~500 MB embedding model is expensive to reload; ChromaDB benefits from
# persistent client reuse as well.
_embedder_cache: SentenceTransformerEmbedder | None = None
_store_cache: ChromaKnowledgeStore | None = None


def _get_or_create_embedder(config: Any) -> SentenceTransformerEmbedder:
    """Return a cached embedder, creating it on first call."""
    from sophia.adapters.embedder import SentenceTransformerEmbedder

    global _embedder_cache
    if _embedder_cache is None:
        _embedder_cache = SentenceTransformerEmbedder(config.embeddings)
    return _embedder_cache


def _get_or_create_store(settings: Any) -> ChromaKnowledgeStore:
    """Return a cached knowledge store, creating it on first call."""
    from sophia.adapters.knowledge_store import ChromaKnowledgeStore

    global _store_cache
    if _store_cache is None:
        _store_cache = ChromaKnowledgeStore(settings.data_dir / "knowledge")
    return _store_cache


async def _get_episode_ids(db: aiosqlite.Connection, module_id: int) -> list[str]:
    """Fetch episode IDs for a module to scope ChromaDB searches."""
    cursor = await db.execute(
        "SELECT episode_id FROM lecture_downloads WHERE module_id = ?",
        (module_id,),
    )
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def _get_material_episode_ids(
    db: aiosqlite.Connection, course_id: int
) -> tuple[list[str], dict[str, str]]:
    """Get material episode IDs and a map of episode_id → material name."""
    cursor = await db.execute(
        "SELECT id, name FROM course_materials WHERE course_id = ? AND status = 'completed'",
        (course_id,),
    )
    rows = await cursor.fetchall()
    ep_ids = [f"mat-{row[0]}" for row in rows]
    name_map = {f"mat-{row[0]}": row[1] for row in rows}
    return ep_ids, name_map


async def _search_material_chunks(
    db: aiosqlite.Connection,
    store: ChromaKnowledgeStore,
    query_embedding: list[float],
    course_id: int,
    *,
    n_results: int = 5,
) -> tuple[list[tuple[KnowledgeChunk, float]], dict[str, str]]:
    """Search PDF material chunks for a course. Returns (results, name_map)."""
    mat_ep_ids, name_map = await _get_material_episode_ids(db, course_id)
    if not mat_ep_ids:
        return [], {}
    results: list[tuple[KnowledgeChunk, float]] = await asyncio.to_thread(
        store.search,
        query_embedding,
        n_results=n_results,
        episode_ids=mat_ep_ids,
        source_filter="pdf",
    )
    return results, name_map


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
    force: bool = False,
) -> list[TopicMapping]:
    """Extract topics from indexed lecture transcripts for a module.

    When ``force=False`` (default) and topics already exist in the DB for this
    module, the LLM call is skipped and the cached topics are returned.  This
    prevents the pipeline and the ``study topics`` CLI command from produing
    mixed-language duplicates when both are run against the same module.

    Pass ``force=True`` (used by the full pipeline after fresh transcription)
    to delete existing topics and re-extract.

    1. Return cached topics if present (unless force=True)
    2. Load transcript segments from DB for the module
    3. Concatenate representative text (budgeted to _MAX_TRANSCRIPT_CHARS)
    4. Call LLM TopicExtractor to get topic labels
    5. Persist to topic_mappings table
    6. Return the extracted topics
    """
    course_id = module_id

    if not force:
        existing = await get_course_topics(app, course_id)
        if existing:
            log.info("topics_cached", module_id=module_id, count=len(existing))
            return existing

    if force:
        await app.db.execute(
            "DELETE FROM topic_mappings WHERE course_id = ? AND source = ?",
            (course_id, TopicSource.LECTURE.value),
        )
        await app.db.commit()

    text = await _get_transcript_text(app.db, module_id)
    if not text:
        log.info("no_transcripts_for_topics", module_id=module_id)
        return []

    if on_progress:
        on_progress("Extracting topics from lecture transcripts…")

    extractor = _create_topic_extractor(app)

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

    config = load_hermes_config(app.settings.config_dir)
    if config is None:
        from sophia.domain.models import HermesConfig

        config = HermesConfig()
    embedder = _get_or_create_embedder(config)
    store = _get_or_create_store(app.settings)

    results: dict[str, list[tuple[KnowledgeChunk, float]]] = {}

    for i, topic in enumerate(topics):
        if on_progress:
            on_progress(topic, i)

        query_embedding: list[float] = await asyncio.to_thread(embedder.embed_query, topic)
        search_results: list[tuple[KnowledgeChunk, float]] = await asyncio.to_thread(
            store.search, query_embedding, n_results=5, episode_ids=episode_ids
        )

        # Also search PDF material chunks
        pdf_results, _ = await _search_material_chunks(
            app.db, store, query_embedding, course_id, n_results=5
        )
        combined = search_results + pdf_results
        results[topic] = combined

        # Persist links
        for chunk, score in combined:
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


async def save_manual_topic(
    app: AppContainer,
    topic: str,
    course_id: int,
) -> TopicMapping | None:
    """Save a user-entered topic with source='manual'. Returns None if empty/duplicate."""
    stripped = topic.strip()
    if not stripped:
        return None

    cursor = await app.db.execute(
        "INSERT OR IGNORE INTO topic_mappings (topic, course_id, source, frequency) "
        "VALUES (?, ?, ?, 1)",
        (stripped, course_id, TopicSource.MANUAL.value),
    )
    await app.db.commit()

    if cursor.rowcount == 0:
        log.debug("manual_topic_duplicate", topic=stripped, course_id=course_id)
        return None

    log.info("manual_topic_saved", topic=stripped, course_id=course_id)
    return TopicMapping(topic=stripped, course_id=course_id, source=TopicSource.MANUAL)


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
    with_provenance: bool = False,
    include_materials: bool = False,
    course_id: int | None = None,
) -> str:
    """Retrieve concatenated lecture transcript chunks relevant to a topic.

    Uses RAG: embed topic → search ChromaDB scoped to module's episodes.
    Returns empty string if no lecture data is available.

    When ``with_provenance=True`` each chunk is prefixed with
    ``[Title, MM:SS]`` so the reader knows its source and timestamp.

    When ``include_materials=True`` PDF material chunks are also searched
    and appended with ``[PDF: name, chunk N]`` provenance annotations.
    """
    episode_ids = await _get_episode_ids(app.db, module_id)
    if not episode_ids:
        return ""

    config = load_hermes_config(app.settings.config_dir)
    if config is None:
        from sophia.domain.models import HermesConfig

        config = HermesConfig()
    embedder = _get_or_create_embedder(config)
    store = _get_or_create_store(app.settings)
    query_embedding = await asyncio.to_thread(embedder.embed_query, topic)
    search_results: list[tuple[KnowledgeChunk, float]] = await asyncio.to_thread(
        store.search, query_embedding, n_results=n_results, episode_ids=episode_ids
    )

    # Optionally search PDF material chunks
    pdf_results: list[tuple[KnowledgeChunk, float]] = []
    mat_name_map: dict[str, str] = {}
    if include_materials and course_id is not None:
        pdf_results, mat_name_map = await _search_material_chunks(
            app.db, store, query_embedding, course_id, n_results=n_results
        )

    if not with_provenance and not include_materials:
        return "\n\n".join(chunk.text for chunk, _score in search_results)

    if not with_provenance:
        all_texts = [chunk.text for chunk, _ in search_results]
        for chunk, _ in pdf_results:
            mat_name = mat_name_map.get(chunk.episode_id, "PDF")
            all_texts.append(f"[PDF: {mat_name}, chunk {chunk.chunk_index}]\n{chunk.text}")
        return "\n\n".join(all_texts)

    # Build episode→title map for lecture chunks
    ep_ids = list({chunk.episode_id for chunk, _ in search_results})
    title_map: dict[str, str] = {}
    if ep_ids:
        placeholders = ",".join("?" * len(ep_ids))
        cursor = await app.db.execute(
            f"SELECT episode_id, title FROM lecture_downloads"  # noqa: S608
            f" WHERE episode_id IN ({placeholders})",
            ep_ids,
        )
        title_map = {row[0]: row[1] for row in await cursor.fetchall()}

    parts: list[str] = []
    for chunk, _ in search_results:
        mm, ss = divmod(int(chunk.start_time), 60)
        raw_title = title_map.get(chunk.episode_id, "Lecture")
        short = raw_title[:25].rstrip() + "…" if len(raw_title) > 25 else raw_title
        parts.append(f"[{short}, {mm:02d}:{ss:02d}]\n{chunk.text}")

    for chunk, _ in pdf_results:
        mat_name = mat_name_map.get(chunk.episode_id, "PDF")
        parts.append(f"[PDF: {mat_name}, chunk {chunk.chunk_index}]\n{chunk.text}")

    return "\n\n".join(parts)


async def generate_study_questions(
    app: AppContainer,
    module_id: int,
    topic: str,
    count: int = 3,
    difficulty: str = "explain",
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
            q = await extractor.generate_question(topic, lecture_context, difficulty=difficulty)
            if q and q not in questions:
                questions.append(q)
        except TopicExtractionError:
            log.warning("question_generation_failed", topic=topic)
            break

    while len(questions) < count:
        questions.append(_FALLBACK_QUESTION.format(topic=topic))

    return questions


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


async def get_failed_review_cards(
    db: aiosqlite.Connection,
    course_id: int,
    topic: str | None = None,
    limit: int = 5,
) -> list[StudentFlashcard]:
    """Get cards that were reviewed and answered incorrectly."""
    query = (
        "SELECT sf.id, sf.course_id, sf.topic, sf.front, sf.back, sf.source, sf.created_at "
        "FROM student_flashcards sf "
        "JOIN card_review_attempts cra ON cra.flashcard_id = sf.id "
        "WHERE sf.course_id = ? AND cra.success = 0 "
    )
    params: list[int | str] = [course_id]
    if topic:
        query += "AND sf.topic = ? "
        params.append(topic)
    query += "GROUP BY sf.id ORDER BY MAX(cra.reviewed_at) DESC LIMIT ?"
    params.append(limit)

    cursor = await db.execute(query, params)
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


# ---------------------------------------------------------------------------
# Self-explanation
# ---------------------------------------------------------------------------

_FULL_SCAFFOLD_PROMPTS = [
    "What fact, rule, or concept did you apply to your answer?",
    "What is different about the correct answer compared to yours?",
    "Give a concrete example that illustrates the correct concept.",
]

_MEDIUM_SCAFFOLD_PROMPTS = [
    "Why was your answer wrong?",
]


async def get_explanation_count(db: aiosqlite.Connection, course_id: int) -> int:
    """Count total self-explanations across all topics for a course."""
    cursor = await db.execute(
        "SELECT COUNT(*) FROM self_explanations se "
        "JOIN student_flashcards sf ON se.flashcard_id = sf.id "
        "WHERE sf.course_id = ?",
        (course_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else 0


def get_scaffold_level(explanation_count: int) -> int:
    """Determine scaffold level based on experience.

    0-9 explanations: level 3 (full scaffolding)
    10-19 explanations: level 1 (minimal scaffolding)
    20+: level 0 (open — student self-regulates)
    """
    if explanation_count < 10:
        return 3
    if explanation_count < 20:
        return 1
    return 0


def get_scaffold_prompts(level: int) -> list[str]:
    """Get the explanation prompts for a given scaffold level."""
    if level >= 3:
        return list(_FULL_SCAFFOLD_PROMPTS)
    if level >= 1:
        return list(_MEDIUM_SCAFFOLD_PROMPTS)
    return []


async def save_self_explanation(
    db: aiosqlite.Connection,
    flashcard_id: int,
    student_explanation: str,
    scaffold_level: int,
) -> SelfExplanation:
    """Save a student's self-explanation for a flashcard."""
    now = datetime.now(UTC).isoformat()
    cursor = await db.execute(
        "INSERT INTO self_explanations "
        "(flashcard_id, student_explanation, scaffold_level, created_at) "
        "VALUES (?, ?, ?, ?)",
        (flashcard_id, student_explanation, scaffold_level, now),
    )
    await db.commit()
    return SelfExplanation(
        id=cursor.lastrowid or 0,
        flashcard_id=flashcard_id,
        student_explanation=student_explanation,
        scaffold_level=scaffold_level,
        created_at=now,
    )


async def get_self_explanations(
    db: aiosqlite.Connection,
    flashcard_id: int,
) -> list[SelfExplanation]:
    """Get all self-explanations for a flashcard."""
    cursor = await db.execute(
        "SELECT id, flashcard_id, student_explanation, scaffold_level, created_at "
        "FROM self_explanations WHERE flashcard_id = ? ORDER BY created_at DESC",
        (flashcard_id,),
    )
    rows = await cursor.fetchall()
    return [
        SelfExplanation(
            id=row[0],
            flashcard_id=row[1],
            student_explanation=row[2],
            scaffold_level=row[3],
            created_at=row[4] or "",
        )
        for row in rows
    ]
