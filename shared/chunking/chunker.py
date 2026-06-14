"""Sentence-boundary-aware text chunker.

The brief: ``TextChunker(chunk_size=512, overlap=50 in TOKENS via
tiktoken cl100k_base)``. Output is a list of ``TextChunk(text,
token_count, chunk_index, source, metadata)``.

The chunker walks the text sentence by sentence (NLTK punkt). When the
running token count exceeds ``chunk_size``, it flushes the current
chunk and starts the next with the last ``overlap`` tokens of the
previous chunk repeated. Sentences are never split across chunks.
Sentences longer than ``chunk_size`` are emitted as their own chunk
(rare in medical prose; a "very long table" case handled by callers
who pre-split tables themselves).

``tiktoken`` is the canonical token counter for MAISYS, per part2 §8.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import tiktoken

# NLTK is heavy to import; do it lazily so callers that only need
# token-counting helpers don't pay the cost.
_nltk_loaded = False


def _ensure_nltk() -> None:
    global _nltk_loaded
    if _nltk_loaded:
        return
    import nltk

    # NLTK's punkt tokenizer is the standard sentence splitter.
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        try:
            nltk.data.find("tokenizers/punkt")
        except LookupError:
            nltk.download("punkt_tab", quiet=True)
    _nltk_loaded = True


@dataclass(frozen=True)
class TextChunk:
    """One emitted chunk."""

    text: str
    token_count: int
    chunk_index: int
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


class TextChunker:
    """Token-aware, sentence-boundary-respecting chunker."""

    def __init__(
        self,
        chunk_size: int = 512,
        overlap: int = 50,
        encoding_name: str = "cl100k_base",
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must satisfy 0 <= overlap < chunk_size")
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._encoder = tiktoken.get_encoding(encoding_name)

    def count_tokens(self, text: str) -> int:
        """Token count via the configured encoding."""
        return len(self._encoder.encode(text))

    def chunk(
        self,
        text: str,
        *,
        source: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[TextChunk]:
        """Split ``text`` into chunks. Empty text yields ``[]``."""
        if not text.strip():
            return []
        _ensure_nltk()
        from nltk.tokenize import sent_tokenize

        sentences = sent_tokenize(text)
        return self._pack(sentences, source=source, metadata=metadata or {})

    def _pack(
        self,
        sentences: list[str],
        *,
        source: str,
        metadata: dict[str, Any],
    ) -> list[TextChunk]:
        chunks: list[TextChunk] = []
        current_tokens: list[int] = []
        current_text: list[str] = []

        for sentence in sentences:
            sent_tokens = self._encoder.encode(sentence)
            if len(sent_tokens) > self._chunk_size:
                # Sentence alone exceeds the budget — flush current,
                # emit the long sentence as its own chunk.
                if current_text:
                    chunks.append(
                        self._build_chunk(
                            current_text, current_tokens, len(chunks), source, metadata
                        )
                    )
                    current_text = []
                    current_tokens = []
                chunks.append(
                    self._build_chunk([sentence], sent_tokens, len(chunks), source, metadata)
                )
                continue

            # +1 space token typically — approximation
            projected = len(current_tokens) + len(sent_tokens)
            if projected > self._chunk_size and current_text:
                chunks.append(
                    self._build_chunk(current_text, current_tokens, len(chunks), source, metadata)
                )
                # Start the next chunk with the last `overlap` tokens of
                # the previous chunk as carry-over context.
                if self._overlap > 0:
                    carry_tokens = current_tokens[-self._overlap :]
                    carry_text = self._encoder.decode(carry_tokens)
                    current_tokens = list(carry_tokens)
                    current_text = [carry_text]
                else:
                    current_tokens = []
                    current_text = []

            current_text.append(sentence)
            current_tokens.extend(sent_tokens)

        if current_text:
            chunks.append(
                self._build_chunk(current_text, current_tokens, len(chunks), source, metadata)
            )
        return chunks

    def _build_chunk(
        self,
        text_parts: list[str],
        tokens: list[int],
        index: int,
        source: str,
        metadata: dict[str, Any],
    ) -> TextChunk:
        return TextChunk(
            text=" ".join(text_parts).strip(),
            token_count=len(tokens),
            chunk_index=index,
            source=source,
            metadata=dict(metadata),
        )


__all__ = ["TextChunk", "TextChunker"]
