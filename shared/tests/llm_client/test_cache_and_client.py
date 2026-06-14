"""Tests for the LLM cache and the top-level client."""

from __future__ import annotations

import pytest

from shared.llm_client import (
    CompletionRequest,
    FakeLLMBackend,
    FakeResponse,
    InMemoryCacheBackend,
    LLMCache,
    LLMClient,
    Message,
    cache_key,
)

# ─── cache_key ────────────────────────────────────────────────────


def test_cache_key_is_deterministic() -> None:
    req = CompletionRequest(
        model="openai/gpt-4o-mini",
        messages=(Message("user", "Hello"),),
        temperature=0.1,
    )
    assert cache_key(req) == cache_key(req)


def test_cache_key_differs_on_model() -> None:
    a = CompletionRequest(model="m1", messages=(Message("user", "x"),))
    b = CompletionRequest(model="m2", messages=(Message("user", "x"),))
    assert cache_key(a) != cache_key(b)


def test_cache_key_differs_on_temperature() -> None:
    a = CompletionRequest(model="m", messages=(Message("user", "x"),), temperature=0.0)
    b = CompletionRequest(model="m", messages=(Message("user", "x"),), temperature=0.7)
    assert cache_key(a) != cache_key(b)


def test_cache_key_independent_of_metadata() -> None:
    """Metadata is informational — it must not affect the cache key."""
    a = CompletionRequest(model="m", messages=(Message("user", "x"),), metadata={"k": "v"})
    b = CompletionRequest(model="m", messages=(Message("user", "x"),), metadata={})
    assert cache_key(a) == cache_key(b)


# ─── LLMCache round-trip ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_miss_returns_none() -> None:
    cache = LLMCache(InMemoryCacheBackend())
    req = CompletionRequest(model="m", messages=(Message("user", "hello"),))
    assert await cache.get(req) is None


@pytest.mark.asyncio
async def test_cache_set_then_get_roundtrips() -> None:
    backend = FakeLLMBackend()
    backend.queue(FakeResponse(content="hi there", prompt_tokens=5, completion_tokens=7))
    cache = LLMCache(InMemoryCacheBackend())
    req = CompletionRequest(model="m", messages=(Message("user", "hello"),))
    response = await backend.complete(req)
    await cache.set(req, response)

    retrieved = await cache.get(req)
    assert retrieved is not None
    assert retrieved.content == "hi there"
    assert retrieved.cached is True
    assert retrieved.usage.total_tokens == 12


# ─── LLMClient end-to-end ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_returns_completion_from_backend() -> None:
    backend = FakeLLMBackend()
    backend.queue(FakeResponse(content="ack", prompt_tokens=3, completion_tokens=1))
    client = LLMClient(backend=backend)
    req = CompletionRequest(model="fake-m", messages=(Message("user", "hi"),))
    response = await client.complete(req)
    assert response.content == "ack"
    assert response.usage.prompt_tokens == 3
    assert response.cached is False


@pytest.mark.asyncio
async def test_client_uses_cache_on_repeat() -> None:
    backend = FakeLLMBackend()
    backend.queue(FakeResponse(content="cached-me"))
    cache = LLMCache(InMemoryCacheBackend())
    client = LLMClient(backend=backend, cache=cache)
    req = CompletionRequest(model="m", messages=(Message("user", "hi"),))

    first = await client.complete(req)
    assert first.cached is False
    assert len(backend.calls) == 1

    second = await client.complete(req)
    assert second.cached is True
    assert second.content == "cached-me"
    # No second call to the backend
    assert len(backend.calls) == 1


@pytest.mark.asyncio
async def test_client_streams_chunks() -> None:
    backend = FakeLLMBackend()
    backend.queue(FakeResponse(content="one two three"))
    client = LLMClient(backend=backend)
    req = CompletionRequest(model="m", messages=(Message("user", "x"),))
    chunks = [c async for c in client.stream(req)]
    assert "".join(chunks).strip() == "one two three"


@pytest.mark.asyncio
async def test_client_propagates_breaker_open_after_failures() -> None:
    backend = FakeLLMBackend()
    for _ in range(5):
        backend.queue(FakeResponse(content="x", raise_exc=RuntimeError("boom")))
    client = LLMClient(backend=backend)
    req = CompletionRequest(model="bad-model", messages=(Message("user", "x"),))
    for _ in range(5):
        with pytest.raises(RuntimeError):
            await client.complete(req)
    # Sixth call: breaker is open
    from shared.error_handler import ExternalServiceException

    with pytest.raises(ExternalServiceException):
        await client.complete(req)
