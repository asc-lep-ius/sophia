"""Sentence-transformers embedding adapter — wraps sentence-transformers with lazy loading.

Implements the ``Embedder`` protocol. sentence-transformers is an optional
dependency; a clear ``EmbeddingError`` is raised if it is missing.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

import structlog

from sophia.domain.errors import EmbeddingError

if TYPE_CHECKING:
    from sophia.domain.models import HermesEmbeddingConfig

log = structlog.get_logger()

_E5_PREFIX_QUERY = "query: "
_E5_PREFIX_PASSAGE = "passage: "


class SentenceTransformerEmbedder:
    """Embedder backed by sentence-transformers with E5 prefix handling.

    ``device`` is passed to sentence-transformers as it is; ``None`` lets it
    pick, which means a CUDA device whenever PyTorch can see one.
    """

    def __init__(self, config: HermesEmbeddingConfig, *, device: str | None = None) -> None:
        self._config = config
        self._device = device
        self._model: Any = None
        # Two first requests at once would otherwise load the model twice.
        self._load_lock = threading.Lock()

    def _ensure_model(self) -> Any:
        """Lazy-load the SentenceTransformer model on first use."""
        with self._load_lock:
            if self._model is None:
                self._model = self._load_model()
            return self._model  # pyright: ignore[reportUnknownVariableType]

    def _load_model(self) -> Any:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
        except ImportError:
            raise EmbeddingError(
                "sentence-transformers not installed — run: uv pip install sophia[hermes]"
            ) from None

        log.info("loading_embedding_model", model=self._config.model, device=self._device)
        try:
            return SentenceTransformer(self._config.model, device=self._device)  # pyright: ignore[reportUnknownVariableType]
        # A model missing from the cache with no network, a device PyTorch has
        # no kernels for: whatever stops the load stops every embedding.
        except Exception as exc:
            raise EmbeddingError(
                f"Embedding model {self._config.model} could not be loaded: {exc}"
            ) from exc

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
