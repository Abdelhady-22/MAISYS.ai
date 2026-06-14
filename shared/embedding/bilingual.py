"""Bilingual (ar / en) embedder.

Wraps two underlying ``Embedder`` instances and routes each input text
to the correct one based on ``langdetect``. Returns vectors grouped
by language so consumers can store them in separate Qdrant
collections.

CRITICAL: Arabic and English embedders MAY have different dimensions
(e.g. text-embedding-3-small is 1536-dim, Arabic-MiniLM-L6-v2 is
384-dim). Vectors from the two languages MUST go to separate Qdrant
collections — they are NOT interchangeable. Consumers should use
collection names like ``drugs_en`` and ``drugs_ar``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from shared.embedding.base import Embedder, Vector
from shared.logger import get_logger

_log = get_logger(__name__)

Language = Literal["en", "ar"]


@dataclass(frozen=True)
class EmbeddedItem:
    """One text with its embedding and detected language."""

    text: str
    language: Language
    vector: Vector
    model_name: str
    original_index: int  # position in the input list


def detect_language(text: str) -> Language:
    """Detect ``en`` vs ``ar`` for one piece of text.

    Returns ``"en"`` as the default when:
    * ``langdetect`` is unavailable (development sandboxes without it)
    * detection raises (very short or non-textual input)
    * detection returns anything other than ``"ar"`` or ``"en"`` (we
      pick the closer of the two by Unicode block)
    """
    try:
        import langdetect

        langdetect.DetectorFactory.seed = 0  # deterministic
        detected = langdetect.detect(text)
    except Exception:
        return _heuristic_language(text)

    if detected == "ar":
        return "ar"
    if detected == "en":
        return "en"
    return _heuristic_language(text)


def _heuristic_language(text: str) -> Language:
    """Fallback: count Arabic-script code points vs total non-space."""
    arabic = sum(1 for c in text if "\u0600" <= c <= "\u06ff")
    non_space = sum(1 for c in text if not c.isspace())
    if non_space == 0:
        return "en"
    return "ar" if arabic / non_space > 0.3 else "en"


class BilingualEmbedder:
    """Routes texts to ar / en embedders and tags each result."""

    def __init__(self, *, en_embedder: Embedder, ar_embedder: Embedder) -> None:
        self._en = en_embedder
        self._ar = ar_embedder
        _log.info(
            "embedding.bilingual.init",
            en_model=en_embedder.model_name,
            en_dim=en_embedder.dimension,
            ar_model=ar_embedder.model_name,
            ar_dim=ar_embedder.dimension,
        )

    @property
    def en_dimension(self) -> int:
        return self._en.dimension

    @property
    def ar_dimension(self) -> int:
        return self._ar.dimension

    async def embed(self, texts: list[str]) -> list[EmbeddedItem]:
        """Embed each text via the appropriate language model.

        Order of the output matches order of the input — even though
        we batch by language internally, the returned list preserves
        the caller's original ordering.
        """
        if not texts:
            return []

        # Partition by detected language, remembering original index.
        en_texts: list[str] = []
        en_indices: list[int] = []
        ar_texts: list[str] = []
        ar_indices: list[int] = []
        for i, text in enumerate(texts):
            lang = detect_language(text)
            if lang == "ar":
                ar_texts.append(text)
                ar_indices.append(i)
            else:
                en_texts.append(text)
                en_indices.append(i)

        # Batch each language to its embedder.
        en_vectors = await self._en.embed(en_texts) if en_texts else []
        ar_vectors = await self._ar.embed(ar_texts) if ar_texts else []

        result: list[EmbeddedItem | None] = [None] * len(texts)
        for idx, vec in zip(en_indices, en_vectors):
            result[idx] = EmbeddedItem(
                text=texts[idx],
                language="en",
                vector=vec,
                model_name=self._en.model_name,
                original_index=idx,
            )
        for idx, vec in zip(ar_indices, ar_vectors):
            result[idx] = EmbeddedItem(
                text=texts[idx],
                language="ar",
                vector=vec,
                model_name=self._ar.model_name,
                original_index=idx,
            )
        assert all(item is not None for item in result)
        return [item for item in result if item is not None]


__all__ = ["BilingualEmbedder", "EmbeddedItem", "Language", "detect_language"]
