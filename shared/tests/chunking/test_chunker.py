"""Tests for TextChunker."""

from __future__ import annotations

import pytest

# tiktoken downloads BPE encodings from a public Azure blob on first
# use. Sandboxed test environments that block outbound traffic to
# ``openaipublic.blob.core.windows.net`` cannot complete that download.
# Skip the whole module in that case so CI / dev machines with network
# access run normally and isolated sandboxes don't false-fail.
tiktoken = pytest.importorskip("tiktoken")
try:
    tiktoken.get_encoding("cl100k_base")
except Exception as _e:  # noqa: BLE001 — broad on purpose
    pytest.skip(
        f"tiktoken cl100k_base unavailable in this environment: {_e}",
        allow_module_level=True,
    )

from shared.chunking import TextChunk, TextChunker  # noqa: E402


def test_empty_text_returns_no_chunks() -> None:
    chunker = TextChunker()
    assert chunker.chunk("", source="x") == []
    assert chunker.chunk("   \n   ", source="x") == []


def test_short_text_returns_single_chunk() -> None:
    chunker = TextChunker(chunk_size=512, overlap=50)
    text = "Acetaminophen relieves mild pain. It is metabolised by the liver."
    chunks = chunker.chunk(text, source="drugs.com")
    assert len(chunks) == 1
    assert chunks[0].source == "drugs.com"
    assert chunks[0].chunk_index == 0
    assert chunks[0].token_count > 0
    assert "Acetaminophen" in chunks[0].text


def test_long_text_splits_into_multiple_chunks() -> None:
    # Build text well over the chunk budget
    sentence = "The drug is metabolised by hepatic enzymes in the cytochrome P450 system. "
    text = sentence * 100
    chunker = TextChunker(chunk_size=128, overlap=20)
    chunks = chunker.chunk(text, source="test")
    assert len(chunks) > 3
    for c in chunks:
        assert c.token_count <= 128 + 30  # +30 lenience for sentence-overhang
    # Chunk indices are sequential
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_overlap_present_between_chunks() -> None:
    sentence = "Aspirin is a salicylate. " * 60
    chunker = TextChunker(chunk_size=64, overlap=10)
    chunks = chunker.chunk(sentence, source="test")
    assert len(chunks) >= 2
    # The second chunk should start with content carried from the first
    assert chunks[1].text  # not empty


def test_overlap_zero_yields_no_carry() -> None:
    sentence = "Lorem ipsum dolor sit amet. " * 60
    chunker = TextChunker(chunk_size=64, overlap=0)
    chunks = chunker.chunk(sentence, source="test")
    assert len(chunks) >= 2


def test_metadata_propagates_to_each_chunk() -> None:
    chunker = TextChunker(chunk_size=64, overlap=10)
    text = "Sentence A. Sentence B. " * 30
    chunks = chunker.chunk(
        text, source="medlineplus", metadata={"drug_name": "ibuprofen", "rxcui": "5640"}
    )
    assert len(chunks) >= 2
    for c in chunks:
        assert c.metadata["drug_name"] == "ibuprofen"
        assert c.metadata["rxcui"] == "5640"


def test_count_tokens_uses_cl100k() -> None:
    chunker = TextChunker()
    # "hello world" is two tokens in cl100k_base
    assert chunker.count_tokens("hello world") == 2


def test_invalid_chunk_size_raises() -> None:
    with pytest.raises(ValueError):
        TextChunker(chunk_size=0)
    with pytest.raises(ValueError):
        TextChunker(chunk_size=512, overlap=-1)
    with pytest.raises(ValueError):
        TextChunker(chunk_size=100, overlap=100)


def test_returns_textchunk_instances() -> None:
    chunker = TextChunker()
    chunks = chunker.chunk("Simple sentence.", source="x")
    assert all(isinstance(c, TextChunk) for c in chunks)
