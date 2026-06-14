"""Sentence-aware text chunking for RAG ingestion.

The default sizing is ``chunk_size=512`` tokens with ``overlap=50``,
counted with tiktoken's ``cl100k_base`` encoding (the encoding used by
all OpenAI and most LiteLLM-supported models). Callers can override
both for per-source tuning — see part2.md §8 for the per-source
target sizes (Drugs.com general 250–400, professional 300–512,
MedlinePlus drugs 250–400, etc.).
"""

from shared.chunking.chunker import TextChunk, TextChunker

__all__ = ["TextChunk", "TextChunker"]
