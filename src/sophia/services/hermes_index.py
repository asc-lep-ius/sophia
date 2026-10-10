"""Hermes indexing orchestration — chunk transcripts, embed, and store in ChromaDB."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from sophia.adapters.embedder import SentenceTransformerEmbedder
from sophia.adapters.knowledge_store import ChromaKnowledgeStore
from sophia.domain.errors import EmbeddingError, LectureIndexUnavailable
from sophia.domain.models import (
    HermesConfig,
    KnowledgeChunk,
    LectureSearchResult,
    TranscriptSegment,
)
from sophia.infra.engine import commit_unit
from sophia.infra.schema import (
    course_materials,
    knowledge_index,
    lecture_downloads,
    transcript_segments,
    transcriptions,
)
from sophia.services.hermes_episodes import episode_title, module_episode_titles_query
from sophia.services.hermes_setup import load_hermes_config

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from sqlalchemy.ext.asyncio import AsyncSession

    from sophia.config import Settings
    from sophia.infra.di import AppContainer

log = structlog.get_logger()

_CHUNK_SIZE = 3
_CHUNK_OVERLAP = 1

QUERY_DEVICE = "cpu"
"""Where a query is embedded: the CPU, whatever the process can see.

The API embeds study topics and search phrases itself (docs/lecture-index-access.md).
One short query takes well under a second there, and it needs no GPU — the
API image has none, and on a GPU PyTorch has no kernels for (hephaestus's
GTX 1070) the default device turned every query into a 500 (#129). The model
is the one the index was built with: both sides read ``[embeddings]`` from the
same ``hermes.toml``.
"""

# One of each per process: the model is ~2 GB and takes seconds to load, and
# chromadb shares one client per path per process anyway.
_query_embedder_cache: SentenceTransformerEmbedder | None = None
_store_cache: ChromaKnowledgeStore | None = None


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


def embedding_config(app: AppContainer) -> HermesConfig:
    """The Hermes config the index is built and queried with; the defaults without one."""
    return load_hermes_config(app.settings.config_dir) or HermesConfig()


def query_embedder(app: AppContainer) -> SentenceTransformerEmbedder:
    """The process's query embedder, on the CPU, created on first use."""
    global _query_embedder_cache
    if _query_embedder_cache is None:
        _query_embedder_cache = SentenceTransformerEmbedder(
            embedding_config(app).embeddings, device=QUERY_DEVICE
        )
    return _query_embedder_cache


def knowledge_store(settings: Settings) -> ChromaKnowledgeStore:
    """The process's one knowledge store, created on first use."""
    global _store_cache
    if _store_cache is None:
        _store_cache = ChromaKnowledgeStore(settings.data_dir / "knowledge")
    return _store_cache


def _create_embedder(app: AppContainer) -> SentenceTransformerEmbedder:
    return SentenceTransformerEmbedder(embedding_config(app).embeddings)


def _create_store(app: AppContainer) -> ChromaKnowledgeStore:
    return knowledge_store(app.settings)


async def _get_transcriptions(session: AsyncSession, module_id: int) -> list[tuple[str, str]]:
    """Return (episode_id, title) for completed transcriptions in a module."""
    rows = (
        await session.execute(
            select(transcriptions.c.episode_id, episode_title().label("title"))
            .outerjoin(
                lecture_downloads,
                transcriptions.c.episode_id == lecture_downloads.c.episode_id,
            )
            .where(
                transcriptions.c.module_id == module_id,
                transcriptions.c.status == "completed",
            )
        )
    ).all()
    return [(row.episode_id, row.title) for row in rows]


async def _get_indexed_ids(session: AsyncSession, module_id: int) -> set[str]:
    query = select(knowledge_index.c.episode_id).where(
        knowledge_index.c.module_id == module_id,
        knowledge_index.c.status == "completed",
    )
    return set((await session.scalars(query)).all())


async def _load_segments(session: AsyncSession, episode_id: str) -> list[TranscriptSegment]:
    rows = (
        await session.execute(
            select(
                transcript_segments.c.start_time,
                transcript_segments.c.end_time,
                transcript_segments.c.text,
            )
            .where(transcript_segments.c.episode_id == episode_id)
            .order_by(transcript_segments.c.segment_index)
        )
    ).all()
    return [
        TranscriptSegment(start=row.start_time, end=row.end_time, text=row.text) for row in rows
    ]


async def _set_index_state(
    session: AsyncSession,
    episode_id: str,
    values: dict[str, object],
) -> None:
    await session.execute(
        update(knowledge_index).where(knowledge_index.c.episode_id == episode_id).values(**values)
    )


async def _index_episode(
    session: AsyncSession,
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

    statement = pg_insert(knowledge_index).values(
        episode_id=episode_id,
        module_id=module_id,
        status="processing",
        created_at=datetime.now(UTC),
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[knowledge_index.c.episode_id],
            set_={
                "module_id": statement.excluded.module_id,
                "status": statement.excluded.status,
                "created_at": statement.excluded.created_at,
                # Re-indexing starts from no result. The SQLite original was an
                # INSERT OR REPLACE, which deleted the row and took these with
                # it; a DO UPDATE that named only the columns above would leave
                # a stale chunk_count and error beside status='processing'.
                "chunk_count": 0,
                "error": None,
                "indexed_at": None,
            },
        )
    )

    try:
        segments = await _load_segments(session, episode_id)
        if not segments:
            await _set_index_state(
                session,
                episode_id,
                {"status": "completed", "chunk_count": 0, "indexed_at": datetime.now(UTC)},
            )
            return IndexingResult(
                episode_id=episode_id, title=title, chunk_count=0, status="completed"
            )

        chunks = chunk_segments(segments, episode_id)
        embeddings: list[list[float]] = await asyncio.to_thread(
            embedder.embed, [c.text for c in chunks]
        )
        await asyncio.to_thread(store.add_chunks, chunks, embeddings)

        await _set_index_state(
            session,
            episode_id,
            {
                "status": "completed",
                "chunk_count": len(chunks),
                "indexed_at": datetime.now(UTC),
            },
        )

        if on_complete:
            on_complete(episode_id, len(chunks))

        log.info("indexing_completed", episode_id=episode_id, chunks=len(chunks))
        return IndexingResult(
            episode_id=episode_id, title=title, chunk_count=len(chunks), status="completed"
        )

    except (EmbeddingError, OSError) as exc:
        await _set_index_state(session, episode_id, {"status": "failed", "error": str(exc)})

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
    session: AsyncSession,
    module_id: int,
    *,
    on_start: Callable[[str, str], None] | None = None,
    on_complete: Callable[[str, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    only_episodes: Collection[str] | None = None,
) -> list[IndexingResult]:
    """Orchestrate indexing for transcribed lectures in a module.

    Queries transcriptions for completed episodes, skips already-indexed ones,
    then chunks, embeds, and stores each episode's segments. Each episode's
    row is committed once its chunks are in the store; an episode interrupted
    in between is indexed again next time, which the store's upsert absorbs.
    ``only_episodes`` narrows the run to those ids.
    """
    transcriptions = await _get_transcriptions(session, module_id)
    if only_episodes is not None:
        transcriptions = [row for row in transcriptions if row[0] in only_episodes]
    if not transcriptions:
        return []

    indexed_ids = await _get_indexed_ids(session, module_id)
    results: list[IndexingResult] = []
    embedder: SentenceTransformerEmbedder | None = None
    store: ChromaKnowledgeStore | None = None

    for episode_id, title in transcriptions:
        if cancel_check and cancel_check():
            log.info("indexing_cancelled", module_id=module_id, completed=len(results))
            break

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
            session,
            embedder,
            store,
            episode_id,
            module_id,
            title,
            on_start=on_start,
            on_complete=on_complete,
        )
        await commit_unit(session)
        results.append(result)

    return results


async def search_lectures(
    app: AppContainer,
    session: AsyncSession,
    module_id: int,
    query: str,
    *,
    n_results: int = 5,
    source_filter: str | None = None,
    course_id: int | None = None,
    missed_only: bool = False,
) -> list[LectureSearchResult]:
    """Semantic search over indexed lecture content.

    Raises ``LectureIndexUnavailable`` when the index cannot be read.
    """
    # Fetch episode IDs for this module to scope the search
    episode_query = module_episode_titles_query(module_id)
    if missed_only:
        episode_query = episode_query.where(lecture_downloads.c.missed_at.is_not(None))

    rows = (await session.execute(episode_query)).all()
    if not rows:
        return []
    title_map = {row.episode_id: row.title for row in rows}
    episode_ids = list(title_map.keys())

    # Include material episode IDs when filtering for PDFs or all sources
    if source_filter != "lecture" and course_id is not None:
        mat_rows = (
            await session.execute(
                select(course_materials.c.id, course_materials.c.name).where(
                    course_materials.c.course_id == course_id,
                )
            )
        ).all()
        for mat_row in mat_rows:
            mat_ep_id = f"mat-{mat_row.id}"
            episode_ids.append(mat_ep_id)
            title_map[mat_ep_id] = mat_row.name

    embedder = query_embedder(app)
    store = knowledge_store(app.settings)
    effective_filter = source_filter if source_filter and source_filter != "all" else None
    try:
        query_embedding: list[float] = await asyncio.to_thread(embedder.embed_query, query)
        search_results = await asyncio.to_thread(
            store.search,
            query_embedding,
            n_results=n_results,
            episode_ids=episode_ids,
            source_filter=effective_filter,
        )
    except EmbeddingError as exc:
        log.warning("lecture_index_unavailable", module_id=module_id, error=str(exc))
        raise LectureIndexUnavailable(str(exc)) from exc

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
            source=chunk.source,
        )
        for chunk, score in search_results
    ]
