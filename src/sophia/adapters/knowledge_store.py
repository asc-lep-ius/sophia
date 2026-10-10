"""ChromaDB knowledge store adapter — persistent vector storage for lecture chunks.

Implements the ``KnowledgeStore`` protocol. chromadb is an optional
dependency; a clear ``EmbeddingError`` is raised if it is missing, and a search
the index cannot answer raises one too.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import structlog

from sophia.domain.errors import EmbeddingError
from sophia.domain.models import KnowledgeChunk

if TYPE_CHECKING:
    from pathlib import Path

log = structlog.get_logger()

_COLLECTION_NAME = "lecture_chunks"
_BATCH_SIZE = 256
# What another process's write to the index touches. Reads leave both alone.
_INDEX_FILES = ("chroma.sqlite3", "chroma.sqlite3-wal")

type _Stamp = tuple[tuple[int, int] | None, ...]


class ChromaKnowledgeStore:
    """KnowledgeStore backed by persistent ChromaDB.

    Meant to be one per process (``hermes_index.knowledge_store``): chromadb
    shares one client per path within a process, and reopening the index
    resets that client for every holder. Calls are serialised for the same
    reason — the API searches from worker threads.
    """

    def __init__(self, persist_dir: Path) -> None:
        self._persist_dir = persist_dir
        self._client: Any = None
        self._collection: Any = None
        self._opened_stamp: _Stamp | None = None
        self._lock = threading.Lock()

    def _stamp(self) -> _Stamp:
        stamps: list[tuple[int, int] | None] = []
        for name in _INDEX_FILES:
            try:
                stat = (self._persist_dir / name).stat()
            except FileNotFoundError:
                stamps.append(None)
            else:
                stamps.append((stat.st_mtime_ns, stat.st_size))
        return tuple(stamps)

    def _is_stale(self) -> bool:
        """Whether somebody else wrote to the index after this store opened it.

        chromadb loads a collection's vectors once per process and never reads
        another process's writes back: an API that had searched once went on
        answering from the index as it was, whatever the worker indexed after
        (#129). The files' stamps are what a write moves, so comparing them
        costs a stat per call and reopens only after a write.
        """
        return self._opened_stamp is not None and self._stamp() != self._opened_stamp

    def _ensure_collection(self) -> Any:
        """Lazy-init ChromaDB client and collection, reopening a stale one."""
        if self._collection is not None and not self._is_stale():
            return self._collection  # pyright: ignore[reportUnknownVariableType]
        try:
            import chromadb  # type: ignore[import-not-found]
            from chromadb.api.client import SharedSystemClient  # type: ignore[import-not-found]
        except ImportError:
            raise EmbeddingError(
                "chromadb not installed — run: uv pip install sophia[hermes]"
            ) from None

        if self._client is not None:
            # A new PersistentClient on the same path would be handed the
            # cached one, stale vectors and all.
            SharedSystemClient.clear_system_cache()  # pyright: ignore[reportUnknownMemberType]
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_dir))  # pyright: ignore[reportUnknownMemberType]
        self._collection = self._client.get_or_create_collection(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            name=_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        self._opened_stamp = self._stamp()
        log.info("chromadb_ready", path=str(self._persist_dir))
        return self._collection  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

    def _note_own_write(self) -> None:
        """Our own writes are already in the vectors we hold; only others' are stale."""
        if self._opened_stamp is not None:
            self._opened_stamp = self._stamp()

    def add_chunks(self, chunks: list[KnowledgeChunk], embeddings: list[list[float]]) -> None:
        """Upsert chunks with their embeddings into the vector store."""
        with self._lock:
            self._add_chunks(chunks, embeddings)
            self._note_own_write()

    def _add_chunks(self, chunks: list[KnowledgeChunk], embeddings: list[list[float]]) -> None:
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
                        "source": c.source,
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
        source_filter: str | None = None,
    ) -> list[tuple[KnowledgeChunk, float]]:
        """Search for similar chunks. Returns (chunk, score) pairs sorted by relevance.

        Raises ``EmbeddingError`` when the index cannot be read: missing,
        corrupt, or built with a model of another dimension.
        """
        with self._lock:
            try:
                return self._search(query_embedding, n_results, episode_ids, source_filter)
            except EmbeddingError:
                raise
            # chromadb raises its own errors and its Rust core's; to the reader
            # every one of them means the same thing.
            except Exception as exc:
                raise EmbeddingError(f"The lecture index could not be read: {exc}") from exc

    def _search(
        self,
        query_embedding: list[float],
        n_results: int,
        episode_ids: list[str] | None,
        source_filter: str | None,
    ) -> list[tuple[KnowledgeChunk, float]]:
        collection = self._ensure_collection()
        where: dict[str, Any] | None = None
        if episode_ids and source_filter:
            where = {"$and": [{"episode_id": {"$in": episode_ids}}, {"source": source_filter}]}
        elif episode_ids:
            where = {"episode_id": {"$in": episode_ids}}
        elif source_filter:
            where = {"source": source_filter}
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
                source=meta.get("source", "lecture"),
            )
            pairs.append((chunk, score))

        return pairs

    def has_episode(self, episode_id: str) -> bool:
        """Check if any chunks exist for the given episode."""
        with self._lock:
            collection = self._ensure_collection()
            results = collection.get(
                where={"episode_id": episode_id},
                limit=1,
                include=[],
            )
            return bool(results["ids"])

    def delete_episode(self, episode_id: str) -> int:
        """Remove all chunks for an episode. Returns the number of chunks deleted."""
        with self._lock:
            collection = self._ensure_collection()
            results = collection.get(where={"episode_id": episode_id}, include=[])
            chunk_ids: list[str] = results["ids"]
            if chunk_ids:
                collection.delete(ids=chunk_ids)
                self._note_own_write()
                log.info("chromadb_episode_deleted", episode_id=episode_id, chunks=len(chunk_ids))
            return len(chunk_ids)
