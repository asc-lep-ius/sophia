"""Hermes indexing orchestration — chunk transcripts, embed, and store in ChromaDB."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from sophia.adapters.embedder import SentenceTransformerEmbedder
from sophia.adapters.knowledge_store import ChromaKnowledgeStore
from sophia.domain.errors import EmbeddingError
from sophia.domain.models import (
    HermesConfig,
    KnowledgeChunk,
    LectureSearchResult,
    TranscriptSegment,
)
from sophia.services.hermes_setup import load_hermes_config

if TYPE_CHECKING:
    from collections.abc import Callable

    import aiosqlite

    from sophia.infra.di import AppContainer

log = structlog.get_logger()

_CHUNK_SIZE = 3
_CHUNK_OVERLAP = 1


@dataclass
class IndexingResult:
    """Outcome of a single episode indexing attempt."""

    episode_id: str
    title: str
    chunk_count: int
    status: str  # "completed", "skipped", "failed"
    error: str | None = None


def chunk_segments(segments: list[TranscriptSegment], episode_id: str) -> list[KnowledgeChunk]:
    """Group transcript segments into overlapping chunks for embedding.

    Uses a sliding window of _CHUNK_SIZE segments with _CHUNK_OVERLAP overlap.
    Each chunk's text is the concatenation of its segments' text.
    """
    if not segments:
        return []

    step = _CHUNK_SIZE - _CHUNK_OVERLAP
    chunks: list[KnowledgeChunk] = []

    for chunk_index, i in enumerate(range(0, len(segments), step)):
        window = segments[i : i + _CHUNK_SIZE]
        # Skip if this window is entirely contained in the previous chunk
        if chunk_index > 0 and len(window) <= _CHUNK_OVERLAP:
            break
        chunks.append(
            KnowledgeChunk(
                chunk_id=f"{episode_id}_{chunk_index}",
                episode_id=episode_id,
                chunk_index=chunk_index,
                text=" ".join(seg.text for seg in window),
                start_time=window[0].start,
                end_time=window[-1].end,
            )
        )

    return chunks


def _create_embedder(app: AppContainer) -> SentenceTransformerEmbedder:
    config = load_hermes_config(app.settings.config_dir)
    if config is None:
        config = HermesConfig()
    return SentenceTransformerEmbedder(config.embeddings)


def _create_store(app: AppContainer) -> ChromaKnowledgeStore:
    return ChromaKnowledgeStore(app.settings.data_dir / "knowledge")


async def _get_transcriptions(db: aiosqlite.Connection, module_id: int) -> list[tuple[str, str]]:
    """Return (episode_id, title) for completed transcriptions in a module."""
    cursor = await db.execute(
        "SELECT t.episode_id, d.title "
        "FROM transcriptions t "
        "JOIN lecture_downloads d ON t.episode_id = d.episode_id "
        "WHERE t.module_id = ? AND t.status = 'completed'",
        (module_id,),
    )
    return await cursor.fetchall()  # type: ignore[return-value]


async def _get_indexed_ids(db: aiosqlite.Connection, module_id: int) -> set[str]:
    cursor = await db.execute(
        "SELECT episode_id FROM knowledge_index WHERE module_id = ? AND status = 'completed'",
        (module_id,),
    )
    rows = await cursor.fetchall()
    return {row[0] for row in rows}


async def _load_segments(db: aiosqlite.Connection, episode_id: str) -> list[TranscriptSegment]:
    cursor = await db.execute(
        "SELECT start_time, end_time, text FROM transcript_segments "
        "WHERE episode_id = ? ORDER BY segment_index",
        (episode_id,),
    )
    rows = await cursor.fetchall()
    return [TranscriptSegment(start=r[0], end=r[1], text=r[2]) for r in rows]


async def _index_episode(
    db: aiosqlite.Connection,
    embedder: SentenceTransformerEmbedder,
    store: ChromaKnowledgeStore,
    episode_id: str,
    module_id: int,
    title: str,
    *,
    on_start: Callable[[str, str], None] | None = None,
    on_complete: Callable[[str, int], None] | None = None,
) -> IndexingResult:
    """Index a single episode: load segments → chunk → embed → store."""
    if on_start:
        on_start(episode_id, title)

    await db.execute(
        "INSERT OR REPLACE INTO knowledge_index "
        "(episode_id, module_id, status, created_at) "
        "VALUES (?, ?, 'processing', datetime('now'))",
        (episode_id, module_id),
    )
    await db.commit()

    try:
        segments = await _load_segments(db, episode_id)
        if not segments:
            await db.execute(
                "UPDATE knowledge_index SET status='completed', chunk_count=0, "
                "indexed_at=datetime('now') WHERE episode_id=?",
                (episode_id,),
            )
            await db.commit()
            return IndexingResult(
                episode_id=episode_id, title=title, chunk_count=0, status="completed"
            )

        chunks = chunk_segments(segments, episode_id)
        embeddings: list[list[float]] = await asyncio.to_thread(
            embedder.embed, [c.text for c in chunks]
        )
        await asyncio.to_thread(store.add_chunks, chunks, embeddings)

        await db.execute(
            "UPDATE knowledge_index SET status='completed', chunk_count=?, "
            "indexed_at=datetime('now') WHERE episode_id=?",
            (len(chunks), episode_id),
        )
        await db.commit()

        if on_complete:
            on_complete(episode_id, len(chunks))

        log.info("indexing_completed", episode_id=episode_id, chunks=len(chunks))
        return IndexingResult(
            episode_id=episode_id, title=title, chunk_count=len(chunks), status="completed"
        )

    except (EmbeddingError, OSError) as exc:
        await db.execute(
            "UPDATE knowledge_index SET status='failed', error=? WHERE episode_id=?",
            (str(exc), episode_id),
        )
        await db.commit()

        log.error("indexing_failed", episode_id=episode_id, error=str(exc))
        return IndexingResult(
            episode_id=episode_id,
            title=title,
            chunk_count=0,
            status="failed",
            error=str(exc),
        )


async def index_lectures(
    app: AppContainer,
    module_id: int,
    *,
    on_start: Callable[[str, str], None] | None = None,
    on_complete: Callable[[str, int], None] | None = None,
) -> list[IndexingResult]:
    """Orchestrate indexing for transcribed lectures in a module.

    Queries transcriptions for completed episodes, skips already-indexed ones,
    then chunks, embeds, and stores each episode's segments.
    """
    transcriptions = await _get_transcriptions(app.db, module_id)
    if not transcriptions:
        return []

    indexed_ids = await _get_indexed_ids(app.db, module_id)
    results: list[IndexingResult] = []
    embedder: SentenceTransformerEmbedder | None = None
    store: ChromaKnowledgeStore | None = None

    for episode_id, title in transcriptions:
        if episode_id in indexed_ids:
            results.append(
                IndexingResult(episode_id=episode_id, title=title, chunk_count=0, status="skipped")
            )
            continue

        if embedder is None:
            embedder = _create_embedder(app)
            store = _create_store(app)

        assert store is not None
        result = await _index_episode(
            app.db,
            embedder,
            store,
            episode_id,
            module_id,
            title,
            on_start=on_start,
            on_complete=on_complete,
        )
        results.append(result)

    return results


async def search_lectures(
    app: AppContainer,
    module_id: int,
    query: str,
    *,
    n_results: int = 5,
) -> list[LectureSearchResult]:
    """Semantic search over indexed lecture content."""
    # Fetch episode IDs for this module to scope the search
    cursor = await app.db.execute(
        "SELECT episode_id, title FROM lecture_downloads WHERE module_id = ?",
        (module_id,),
    )
    rows = await cursor.fetchall()
    if not rows:
        return []
    title_map = {row[0]: row[1] for row in rows}
    episode_ids = list(title_map.keys())

    embedder = _create_embedder(app)
    store = _create_store(app)

    query_embedding: list[float] = await asyncio.to_thread(embedder.embed_query, query)
    search_results = await asyncio.to_thread(
        store.search, query_embedding, n_results=n_results, episode_ids=episode_ids
    )

    if not search_results:
        return []

    return [
        LectureSearchResult(
            episode_id=chunk.episode_id,
            title=title_map.get(chunk.episode_id, "Unknown"),
            chunk_text=chunk.text,
            start_time=chunk.start_time,
            end_time=chunk.end_time,
            score=score,
        )
        for chunk, score in search_results
    ]
