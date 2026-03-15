"""Athena study service — topic extraction and lecture cross-referencing."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from sophia.adapters.topic_extractor import LLMTopicExtractor
from sophia.domain.errors import TopicExtractionError
from sophia.domain.models import KnowledgeChunk, TopicMapping, TopicSource
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
