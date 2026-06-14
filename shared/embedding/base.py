"""Shared embedding types, protocol, and deterministic fake.

The ``Embedder`` protocol is the minimal contract every embedding
backend implements: a single async ``embed(texts) -> list[Vector]``.
Vectors are plain ``list[float]``; numpy is intentionally avoided
at the public boundary so callers don't need to install it.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, runtime_checkable

Vector = list[float]


@runtime_checkable
class Embedder(Protocol):
    """An async embedding backend.

    Implementations:

    * ``LiteLLMEmbedder`` — production English (text-embedding-3-small).
    * ``SentenceTransformerEmbedder`` — production Arabic via the
      Omartificial Arabic-MiniLM model.
    * ``FakeEmbedder`` — deterministic, no-network embedder for tests.
    """

    @property
    def dimension(self) -> int: ...
    @property
    def model_name(self) -> str: ...
    async def embed(self, texts: list[str]) -> list[Vector]: ...


class FakeEmbedder:
    """Deterministic embedder for tests.

    Vector[i] = (hash(text) >> i) / max_uint64 — produces a
    repeatable, unit-magnitude vector keyed by the input string. Two
    identical inputs always get identical vectors; different inputs
    always get different vectors (collisions are astronomically rare).
    """

    def __init__(self, *, dimension: int = 32, model_name: str = "fake-embedder") -> None:
        if dimension <= 0:
            raise ValueError("dimension must be positive")
        self._dimension = dimension
        self._model_name = model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name

    async def embed(self, texts: list[str]) -> list[Vector]:
        return [self._vector_for(text) for text in texts]

    def _vector_for(self, text: str) -> Vector:
        # SHA-256 over the text gives 32 bytes — repeat the hash to
        # fill the desired dimension, then normalise to unit length.
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        floats: list[float] = []
        i = 0
        while len(floats) < self._dimension:
            byte = digest[i % len(digest)]
            # Map 0..255 to -1..+1 evenly
            floats.append((byte - 127.5) / 127.5)
            i += 1
        # L2-normalise so cosine similarity is well-defined
        norm = math.sqrt(sum(f * f for f in floats)) or 1.0
        return [f / norm for f in floats]


__all__ = ["Embedder", "FakeEmbedder", "Vector"]
