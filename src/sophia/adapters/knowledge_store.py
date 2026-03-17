"""ChromaDB knowledge store adapter — persistent vector storage for lecture chunks.

Implements the ``KnowledgeStore`` protocol. chromadb is an optional
dependency; a clear ``EmbeddingError`` is raised if it is missing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from sophia.domain.errors import EmbeddingError
from sophia.domain.models import KnowledgeChunk

if TYPE_CHECKING:
    from pathlib import Path

log = structlog.get_logger()

_COLLECTION_NAME = "lecture_chunks"
_BATCH_SIZE = 256


class ChromaKnowledgeStore:
    """KnowledgeStore backed by persistent ChromaDB."""

    def __init__(self, persist_dir: Path) -> None:
        self._persist_dir = persist_dir
        self._client: Any = None
        self._collection: Any = None

    def _ensure_collection(self) -> Any:
        """Lazy-init ChromaDB client and collection."""
        if self._collection is not None:
            return self._collection  # pyright: ignore[reportUnknownVariableType]
        try:
            import chromadb  # type: ignore[import-not-found]
        except ImportError:
            raise EmbeddingError(
                "chromadb not installed — run: uv pip install sophia[hermes]"
            ) from None

        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_dir))  # pyright: ignore[reportUnknownMemberType]
        self._collection = self._client.get_or_create_collection(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        log.info("chromadb_ready", path=str(self._persist_dir))
        return self._collection  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

    def add_chunks(self, chunks: list[KnowledgeChunk], embeddings: list[list[float]]) -> None:
        """Upsert chunks with their embeddings into the vector store."""
        collection = self._ensure_collection()
        for i in range(0, len(chunks), _BATCH_SIZE):
            batch_chunks = chunks[i : i + _BATCH_SIZE]
            batch_embeddings = embeddings[i : i + _BATCH_SIZE]
            collection.upsert(
                ids=[c.chunk_id for c in batch_chunks],
                embeddings=batch_embeddings,
                documents=[c.text for c in batch_chunks],
                metadatas=[
                    {
                        "episode_id": c.episode_id,
                        "chunk_index": c.chunk_index,
                        "start_time": c.start_time,
                        "end_time": c.end_time,
                    }
                    for c in batch_chunks
                ],
            )

    def search(
        self,
        query_embedding: list[float],
        *,
        n_results: int = 5,
        episode_ids: list[str] | None = None,
    ) -> list[tuple[KnowledgeChunk, float]]:
        """Search for similar chunks. Returns (chunk, score) pairs sorted by relevance."""
        collection = self._ensure_collection()
        where = {"episode_id": {"$in": episode_ids}} if episode_ids else None
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        pairs: list[tuple[KnowledgeChunk, float]] = []
        if not results["ids"] or not results["ids"][0]:
            return pairs

        for idx, chunk_id in enumerate(results["ids"][0]):
            meta = results["metadatas"][0][idx]
            doc = results["documents"][0][idx]
            distance = results["distances"][0][idx]
            score = 1.0 - distance
            chunk = KnowledgeChunk(
                chunk_id=chunk_id,
                episode_id=meta["episode_id"],
                chunk_index=meta["chunk_index"],
                text=doc,
                start_time=meta["start_time"],
                end_time=meta["end_time"],
            )
            pairs.append((chunk, score))

        return pairs

    def has_episode(self, episode_id: str) -> bool:
        """Check if any chunks exist for the given episode."""
        collection = self._ensure_collection()
        results = collection.get(
            where={"episode_id": episode_id},
            limit=1,
            include=[],
        )
        return bool(results["ids"])

    def delete_episode(self, episode_id: str) -> int:
        """Remove all chunks for an episode. Returns the number of chunks deleted."""
        collection = self._ensure_collection()
        results = collection.get(where={"episode_id": episode_id}, include=[])
        chunk_ids: list[str] = results["ids"]
        if chunk_ids:
            collection.delete(ids=chunk_ids)
            log.info("chromadb_episode_deleted", episode_id=episode_id, chunks=len(chunk_ids))
        return len(chunk_ids)
