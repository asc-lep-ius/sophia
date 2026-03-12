"""Sentence-transformers embedding adapter — wraps sentence-transformers with lazy loading.

Implements the ``Embedder`` protocol. sentence-transformers is an optional
dependency; a clear ``EmbeddingError`` is raised if it is missing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from sophia.domain.errors import EmbeddingError

if TYPE_CHECKING:
    from sophia.domain.models import HermesEmbeddingConfig

log = structlog.get_logger()

_E5_PREFIX_QUERY = "query: "
_E5_PREFIX_PASSAGE = "passage: "


class SentenceTransformerEmbedder:
    """Embedder backed by sentence-transformers with E5 prefix handling."""

    def __init__(self, config: HermesEmbeddingConfig) -> None:
        self._config = config
        self._model: Any = None

    def _ensure_model(self) -> Any:
        """Lazy-load the SentenceTransformer model on first use."""
        if self._model is not None:
            return self._model  # pyright: ignore[reportUnknownVariableType]
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError:
            raise EmbeddingError(
                "sentence-transformers not installed — run: uv pip install sophia[hermes]"
            ) from None

        log.info("loading_embedding_model", model=self._config.model)
        self._model = SentenceTransformer(self._config.model)  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        return self._model  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

    @property
    def _is_e5(self) -> bool:
        return "e5" in self._config.model.lower()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into dense vectors."""
        model = self._ensure_model()
        prefixed = [f"{_E5_PREFIX_PASSAGE}{t}" for t in texts] if self._is_e5 else texts
        try:
            embeddings = model.encode(prefixed, normalize_embeddings=True)
            return [emb.tolist() for emb in embeddings]
        except Exception as exc:
            raise EmbeddingError(str(exc)) from exc

    def embed_query(self, query: str) -> list[float]:
        """Embed a single search query with appropriate prefix."""
        model = self._ensure_model()
        prefixed = f"{_E5_PREFIX_QUERY}{query}" if self._is_e5 else query
        try:
            embedding = model.encode([prefixed], normalize_embeddings=True)
            return embedding[0].tolist()
        except Exception as exc:
            raise EmbeddingError(str(exc)) from exc
