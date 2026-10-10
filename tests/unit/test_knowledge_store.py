"""Tests for the ChromaDB knowledge store adapter."""

from __future__ import annotations

import subprocess
import sys
import textwrap
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

    def test_delete_episode_removes_chunks(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": ["ep-001_0", "ep-001_1", "ep-001_2"]}

        store = ChromaKnowledgeStore(tmp_path / "chroma")
        store._collection = mock_collection  # pyright: ignore[reportPrivateUsage]

        count = store.delete_episode("ep-001")

        assert count == 3
        mock_collection.get.assert_called_once_with(where={"episode_id": "ep-001"}, include=[])
        mock_collection.delete.assert_called_once_with(ids=["ep-001_0", "ep-001_1", "ep-001_2"])

    def test_delete_episode_returns_zero_for_nonexistent(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}

        store = ChromaKnowledgeStore(tmp_path / "chroma")
        store._collection = mock_collection  # pyright: ignore[reportPrivateUsage]

        count = store.delete_episode("no-such-ep")

        assert count == 0
        mock_collection.delete.assert_not_called()

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

    def test_add_chunks_includes_source_in_metadata(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        mock_collection = MagicMock()
        store = ChromaKnowledgeStore(tmp_path / "chroma")
        store._collection = mock_collection  # pyright: ignore[reportPrivateUsage]

        chunks = [
            _make_chunk(chunk_index=0),
            KnowledgeChunk(
                chunk_id="ep-001_1",
                episode_id="ep-001",
                chunk_index=1,
                text="PDF content",
                start_time=5.0,
                end_time=10.0,
                source="pdf",
            ),
        ]
        embeddings = [[0.1, 0.2], [0.3, 0.4]]
        store.add_chunks(chunks, embeddings)

        call_kwargs = mock_collection.upsert.call_args[1]
        metadatas = call_kwargs["metadatas"]
        assert metadatas[0]["source"] == "lecture"
        assert metadatas[1]["source"] == "pdf"

    def test_search_with_source_filter_only(self, tmp_path: Path) -> None:
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

        store.search([0.5, 0.6], source_filter="pdf")

        call_kwargs = mock_collection.query.call_args[1]
        assert call_kwargs["where"] == {"source": "pdf"}

    def test_search_with_episode_ids_and_source_filter(self, tmp_path: Path) -> None:
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

        store.search([0.5, 0.6], episode_ids=["ep-001"], source_filter="pdf")

        call_kwargs = mock_collection.query.call_args[1]
        assert call_kwargs["where"] == {
            "$and": [
                {"episode_id": {"$in": ["ep-001"]}},
                {"source": "pdf"},
            ]
        }

    def test_search_without_source_filter_backward_compat(self, tmp_path: Path) -> None:
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

        store.search([0.5, 0.6], episode_ids=["ep-001"])

        call_kwargs = mock_collection.query.call_args[1]
        assert call_kwargs["where"] == {"episode_id": {"$in": ["ep-001"]}}


class _FakeChroma:
    """A ``chromadb`` module that counts clients and system-cache resets."""

    def __init__(self) -> None:
        self.clients: list[MagicMock] = []
        self.cache_clears = 0
        self.module = MagicMock()
        self.module.PersistentClient.side_effect = self._client
        self.api_client = MagicMock()
        self.api_client.SharedSystemClient.clear_system_cache.side_effect = self._clear

    def _client(self, path: str) -> MagicMock:
        client = MagicMock(name=f"client-{len(self.clients)}")
        collection = client.get_or_create_collection.return_value
        collection.query.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]]}
        self.clients.append(client)
        return client

    def _clear(self) -> None:
        self.cache_clears += 1

    def modules(self) -> dict[str, object]:
        return {"chromadb": self.module, "chromadb.api.client": self.api_client}


class TestAnotherProcessWritingTheIndex:
    """The API reads the index the worker writes (#129)."""

    def test_a_write_by_another_process_reopens_the_index(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        chroma = _FakeChroma()
        store = ChromaKnowledgeStore(tmp_path)
        (tmp_path / "chroma.sqlite3").write_bytes(b"one lecture")
        with patch.dict("sys.modules", chroma.modules()):
            store.search([0.1, 0.2])
            store.search([0.1, 0.2])
            assert (len(chroma.clients), chroma.cache_clears) == (1, 0)

            # The worker indexed another lecture.
            (tmp_path / "chroma.sqlite3").write_bytes(b"one lecture, then another")
            store.search([0.1, 0.2])

        assert (len(chroma.clients), chroma.cache_clears) == (2, 1)

    def test_its_own_writes_do_not_reopen_it(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        chroma = _FakeChroma()
        store = ChromaKnowledgeStore(tmp_path)
        with patch.dict("sys.modules", chroma.modules()):
            store.search([0.1, 0.2])
            collection = chroma.clients[0].get_or_create_collection.return_value
            collection.upsert.side_effect = lambda **_: (tmp_path / "chroma.sqlite3").write_bytes(
                b"written by add_chunks"
            )
            store.add_chunks([_make_chunk()], [[0.1, 0.2]])
            store.search([0.1, 0.2])

        assert (len(chroma.clients), chroma.cache_clears) == (1, 0)

    def test_an_index_that_cannot_be_searched_is_an_embedding_error(self, tmp_path: Path) -> None:
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        mock_collection = MagicMock()
        mock_collection.query.side_effect = ValueError(
            "Collection expecting embedding with dimension of 1024, got 384"
        )
        store = ChromaKnowledgeStore(tmp_path)
        store._collection = mock_collection  # pyright: ignore[reportPrivateUsage]

        with pytest.raises(EmbeddingError, match="could not be read: Collection expecting"):
            store.search([0.1] * 384)

    def test_a_real_reader_sees_what_another_process_indexed_after_it(self, tmp_path: Path) -> None:
        """chromadb itself: without the reopen, the second search misses lecture two."""
        pytest.importorskip("chromadb")
        from sophia.adapters.knowledge_store import ChromaKnowledgeStore

        writer = textwrap.dedent(
            """
            import sys
            from pathlib import Path
            from sophia.adapters.knowledge_store import ChromaKnowledgeStore
            from sophia.domain.models import KnowledgeChunk

            store = ChromaKnowledgeStore(Path(sys.argv[1]))
            n = int(sys.argv[2])
            chunk = KnowledgeChunk(
                chunk_id=f"lecture-{n}_0", episode_id=f"lecture-{n}", chunk_index=0,
                text=f"lecture {n}", start_time=0.0, end_time=5.0,
            )
            store.add_chunks([chunk], [[1.0, float(n), 0.0]])
            """
        )
        subprocess.run([sys.executable, "-c", writer, str(tmp_path), "1"], check=True)
        reader = ChromaKnowledgeStore(tmp_path)
        assert [c.episode_id for c, _ in reader.search([1.0, 2.0, 0.0], n_results=5)] == [
            "lecture-1"
        ]

        subprocess.run([sys.executable, "-c", writer, str(tmp_path), "2"], check=True)
        found = [c.episode_id for c, _ in reader.search([1.0, 2.0, 0.0], n_results=5)]

        assert found == ["lecture-2", "lecture-1"]
