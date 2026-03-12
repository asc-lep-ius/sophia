"""Tests for the ChromaDB knowledge store adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from sophia.domain.errors import EmbeddingError
from sophia.domain.models import KnowledgeChunk

if TYPE_CHECKING:
    from pathlib import Path


def _make_chunk(
    episode_id: str = "ep-001",
    chunk_index: int = 0,
    text: str = "Hello world",
    start_time: float = 0.0,
    end_time: float = 5.0,
) -> KnowledgeChunk:
    return KnowledgeChunk(
        chunk_id=f"{episode_id}_{chunk_index}",
        episode_id=episode_id,
        chunk_index=chunk_index,
        text=text,
        start_time=start_time,
        end_time=end_time,
    )


class TestChromaKnowledgeStore:
    """Tests for ChromaKnowledgeStore."""

    def test_import_error_raises_embedding_error(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        store = ChromaKnowledgeStore(tmp_path / "chroma")
        with (
            patch.dict("sys.modules", {"chromadb": None}),
            pytest.raises(EmbeddingError, match="chromadb not installed"),
        ):
            store.has_episode("ep-001")

    def test_add_chunks_upserts_to_collection(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        mock_collection = MagicMock()
        store = ChromaKnowledgeStore(tmp_path / "chroma")
        store._collection = mock_collection  # pyright: ignore[reportPrivateUsage]

        chunks = [_make_chunk(chunk_index=0), _make_chunk(chunk_index=1)]
        embeddings = [[0.1, 0.2], [0.3, 0.4]]
        store.add_chunks(chunks, embeddings)

        mock_collection.upsert.assert_called_once()
        call_kwargs = mock_collection.upsert.call_args[1]
        assert len(call_kwargs["ids"]) == 2
        assert len(call_kwargs["embeddings"]) == 2

    def test_search_returns_chunks_with_scores(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["ep-001_0", "ep-001_1"]],
            "documents": [["Hello world", "Second chunk"]],
            "metadatas": [
                [
                    {"episode_id": "ep-001", "chunk_index": 0, "start_time": 0.0, "end_time": 5.0},
                    {
                        "episode_id": "ep-001",
                        "chunk_index": 1,
                        "start_time": 5.0,
                        "end_time": 10.0,
                    },
                ]
            ],
            "distances": [[0.1, 0.3]],
        }

        store = ChromaKnowledgeStore(tmp_path / "chroma")
        store._collection = mock_collection  # pyright: ignore[reportPrivateUsage]

        results = store.search([0.5, 0.6], n_results=2)

        assert len(results) == 2
        chunk, score = results[0]
        assert chunk.episode_id == "ep-001"
        assert chunk.text == "Hello world"
        assert score == pytest.approx(0.9)  # pyright: ignore[reportUnknownMemberType]

    def test_search_empty_results(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

        store = ChromaKnowledgeStore(tmp_path / "chroma")
        store._collection = mock_collection  # pyright: ignore[reportPrivateUsage]

        results = store.search([0.5, 0.6])
        assert results == []

    def test_search_with_episode_ids_filter(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [["ep-001_0"]],
            "documents": [["Hello world"]],
            "metadatas": [
                [{"episode_id": "ep-001", "chunk_index": 0, "start_time": 0.0, "end_time": 5.0}]
            ],
            "distances": [[0.1]],
        }

        store = ChromaKnowledgeStore(tmp_path / "chroma")
        store._collection = mock_collection  # pyright: ignore[reportPrivateUsage]

        store.search([0.5, 0.6], n_results=2, episode_ids=["ep-001", "ep-002"])

        call_kwargs = mock_collection.query.call_args[1]
        assert call_kwargs["where"] == {"episode_id": {"$in": ["ep-001", "ep-002"]}}

    def test_search_without_episode_ids_no_where(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

        store = ChromaKnowledgeStore(tmp_path / "chroma")
        store._collection = mock_collection  # pyright: ignore[reportPrivateUsage]

        store.search([0.5, 0.6])

        call_kwargs = mock_collection.query.call_args[1]
        assert call_kwargs.get("where") is None

    def test_has_episode_true(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": ["ep-001_0"]}

        store = ChromaKnowledgeStore(tmp_path / "chroma")
        store._collection = mock_collection  # pyright: ignore[reportPrivateUsage]

        assert store.has_episode("ep-001") is True

    def test_has_episode_false(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}

        store = ChromaKnowledgeStore(tmp_path / "chroma")
        store._collection = mock_collection  # pyright: ignore[reportPrivateUsage]

        assert store.has_episode("ep-001") is False
