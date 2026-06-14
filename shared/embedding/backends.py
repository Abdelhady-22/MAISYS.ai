"""Production embedding backends.

Two backends ship today:

* ``LiteLLMEmbedder`` — calls a LiteLLM ``aembedding`` endpoint. Default
  model is ``openai/text-embedding-3-small`` (1536-dim). The provider
  is implicit in the model string (``openai/...``, ``azure/...``,
  etc.).
* ``SentenceTransformerEmbedder`` — local model via the
  ``sentence-transformers`` package. Used for Arabic
  (``Omartificial-Intelligence-Space/Arabic-MiniLM-L6-v2``, 384-dim)
  and any offline-friendly English fallback (``all-MiniLM-L6-v2``,
  also 384-dim).

Both are imported lazily so callers that only use ``FakeEmbedder`` in
tests don't pay the import cost.
"""

from __future__ import annotations

from typing import Any

from shared.embedding.base import Vector
from shared.logger import get_logger

_log = get_logger(__name__)


class LiteLLMEmbedder:
    """Async embedder backed by LiteLLM's unified ``aembedding`` API."""

    def __init__(
        self, *, model: str = "openai/text-embedding-3-small", dimension: int = 1536
    ) -> None:
        import importlib

        self._litellm = importlib.import_module("litellm")
        self._model = model
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model

    async def embed(self, texts: list[str]) -> list[Vector]:
        if not texts:
            return []
        raw: dict[str, Any] = await self._litellm.aembedding(model=self._model, input=texts)
        vectors: list[Vector] = []
        for entry in raw["data"]:
            embedding = entry["embedding"]
            vectors.append([float(x) for x in embedding])
        return vectors


class SentenceTransformerEmbedder:
    """Local sentence-transformers embedder (no network at inference time)."""

    def __init__(self, *, model: str, dimension: int) -> None:
        import importlib

        st = importlib.import_module("sentence_transformers")
        self._model_name = model
        self._dimension = dimension
        # SentenceTransformer is synchronous; we wrap calls in
        # asyncio.to_thread so we don't block the event loop on
        # CPU-bound encoding.
        self._model = st.SentenceTransformer(model)
        _log.info("embedding.st.loaded", model=model, dimension=dimension)

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    async def embed(self, texts: list[str]) -> list[Vector]:
        if not texts:
            return []
        import asyncio

        def _encode() -> list[Vector]:
            arrays = self._model.encode(texts, normalize_embeddings=True)
            return [list(map(float, row)) for row in arrays]

        return await asyncio.to_thread(_encode)


__all__ = ["LiteLLMEmbedder", "SentenceTransformerEmbedder"]
