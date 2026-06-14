"""Bilingual (ar + en) embedding with pluggable backends.

Public surface:

* ``Embedder`` — async embedder protocol.
* ``BilingualEmbedder`` — routes between an en and ar embedder via langdetect.
* ``EmbeddedItem`` — one (text, language, vector) result.
* ``FakeEmbedder`` — deterministic test fake.
* ``LiteLLMEmbedder`` — production English (text-embedding-3-small).
* ``SentenceTransformerEmbedder`` — production Arabic (Arabic-MiniLM-L6-v2)
  and any local English fallback.
* ``detect_language(text)`` — exposed for callers that need just the
  detection.

IMPORTANT: English and Arabic embedders typically have different
vector dimensions. Consumers MUST store the vectors in separate
Qdrant collections (``drugs_en`` / ``drugs_ar`` etc.) — vectors are
not comparable across the two collections.
"""

from shared.embedding.backends import LiteLLMEmbedder, SentenceTransformerEmbedder
from shared.embedding.base import Embedder, FakeEmbedder, Vector
from shared.embedding.bilingual import (
    BilingualEmbedder,
    EmbeddedItem,
    Language,
    detect_language,
)

__all__ = [
    "BilingualEmbedder",
    "EmbeddedItem",
    "Embedder",
    "FakeEmbedder",
    "Language",
    "LiteLLMEmbedder",
    "SentenceTransformerEmbedder",
    "Vector",
    "detect_language",
]
