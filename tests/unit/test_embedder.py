"""Tests for the sentence-transformers embedding adapter."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from sophia.domain.errors import EmbeddingError
from sophia.domain.models import EmbeddingProvider, HermesEmbeddingConfig


class _FakeNdArray:
    """Minimal ndarray stand-in for testing: supports iteration, indexing, and tolist()."""

    def __init__(self, data: list[Any]) -> None:
        self._data = data

    def __iter__(self):  # pyright: ignore[reportUnknownParameterType]
        return iter(_FakeNdArray(row) if isinstance(row, list) else row for row in self._data)  # pyright: ignore[reportUnknownArgumentType]

    def __getitem__(self, idx: int) -> _FakeNdArray:
        item = self._data[idx]
        return _FakeNdArray(item) if isinstance(item, list) else item  # pyright: ignore[reportReturnType, reportUnknownArgumentType]

    def tolist(self) -> list[Any]:
        return self._data

    def __len__(self) -> int:
        return len(self._data)


def _make_config(model: str = "intfloat/multilingual-e5-large") -> HermesEmbeddingConfig:
    return HermesEmbeddingConfig(provider=EmbeddingProvider.LOCAL, model=model)


class TestSentenceTransformerEmbedder:
    """Tests for SentenceTransformerEmbedder."""

    def test_import_error_raises_embedding_error(self) -> None:
        from sophia.adapters.embedder import SentenceTransformerEmbedder

        embedder = SentenceTransformerEmbedder(_make_config())
        with (
            patch.dict("sys.modules", {"sentence_transformers": None}),
            pytest.raises(EmbeddingError, match="sentence-transformers not installed"),
        ):
            embedder.embed(["test"])

    def test_embed_e5_adds_passage_prefix(self) -> None:
        from sophia.adapters.embedder import SentenceTransformerEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = _FakeNdArray([[0.1, 0.2], [0.3, 0.4]])

        embedder = SentenceTransformerEmbedder(_make_config("intfloat/multilingual-e5-large"))
        embedder._model = mock_model  # pyright: ignore[reportPrivateUsage]

        result = embedder.embed(["hello", "world"])
        assert len(result) == 2
        call_args = mock_model.encode.call_args
        assert call_args[0][0] == ["passage: hello", "passage: world"]

    def test_embed_non_e5_no_prefix(self) -> None:
        from sophia.adapters.embedder import SentenceTransformerEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = _FakeNdArray([[0.1, 0.2]])

        embedder = SentenceTransformerEmbedder(_make_config("all-MiniLM-L6-v2"))
        embedder._model = mock_model  # pyright: ignore[reportPrivateUsage]

        result = embedder.embed(["hello"])
        assert len(result) == 1
        call_args = mock_model.encode.call_args
        assert call_args[0][0] == ["hello"]

    def test_embed_query_e5_adds_query_prefix(self) -> None:
        from sophia.adapters.embedder import SentenceTransformerEmbedder

        mock_model = MagicMock()
        mock_model.encode.return_value = _FakeNdArray([[0.5, 0.6]])

        embedder = SentenceTransformerEmbedder(_make_config())
        embedder._model = mock_model  # pyright: ignore[reportPrivateUsage]

        result = embedder.embed_query("what is AI?")
        assert len(result) == 2
        call_args = mock_model.encode.call_args
        assert call_args[0][0] == ["query: what is AI?"]

    def test_embed_exception_wraps_in_embedding_error(self) -> None:
        from sophia.adapters.embedder import SentenceTransformerEmbedder

        mock_model = MagicMock()
        mock_model.encode.side_effect = RuntimeError("GPU OOM")

        embedder = SentenceTransformerEmbedder(_make_config())
        embedder._model = mock_model  # pyright: ignore[reportPrivateUsage]

        with pytest.raises(EmbeddingError, match="GPU OOM"):
            embedder.embed(["test"])
