"""Top-level LLM client that wires backend, cache, and circuit breaker.

Usage::

    from shared.llm_client import LLMClient, CompletionRequest, Message

    client = LLMClient.from_env()  # uses LiteLLM + Redis cache
    resp = await client.complete(CompletionRequest(
        model="openai/gpt-4o-mini",
        messages=(Message("user", "Hello"),),
    ))

In tests, swap the backend and use the in-memory cache:

    client = LLMClient(
        backend=FakeLLMBackend(),
        cache=LLMCache(InMemoryCacheBackend()),
    )
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from shared.llm_client.backends import Backend, LiteLLMBackend
from shared.llm_client.cache import CacheBackend, InMemoryCacheBackend, LLMCache
from shared.llm_client.circuit_breaker import CircuitBreaker
from shared.llm_client.types import CompletionRequest, CompletionResponse
from shared.logger import get_logger

_log = get_logger(__name__)


class LLMClient:
    """Production-grade LLM client with cache and breaker around any backend."""

    def __init__(
        self,
        *,
        backend: Backend,
        cache: LLMCache | None = None,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._backend = backend
        self._cache = cache
        self._breaker = breaker or CircuitBreaker()

    @classmethod
    def from_env(cls) -> LLMClient:
        """Construct a production client from environment variables.

        - ``LLM_CACHE_REDIS_URL`` enables the Redis cache when set
          (e.g. ``redis://redis:6379/2``). Absent → no cache.
        - ``LLM_CACHE_TTL_SECONDS`` overrides the default 3600.
        - ``LLM_BREAKER_FAILURE_THRESHOLD`` overrides 5.
        - ``LLM_BREAKER_COOLDOWN_SECONDS`` overrides 60.
        """
        cache: LLMCache | None = None
        redis_url = os.environ.get("LLM_CACHE_REDIS_URL")
        if redis_url:
            cache_backend = _build_redis_cache_backend(redis_url)
            ttl = int(os.environ.get("LLM_CACHE_TTL_SECONDS", "3600"))
            cache = LLMCache(cache_backend, ttl_seconds=ttl)

        breaker = CircuitBreaker(
            failure_threshold=int(os.environ.get("LLM_BREAKER_FAILURE_THRESHOLD", "5")),
            cooldown_seconds=float(os.environ.get("LLM_BREAKER_COOLDOWN_SECONDS", "60")),
        )
        return cls(backend=LiteLLMBackend(), cache=cache, breaker=breaker)

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Run a chat-completion. Honours cache, breaker, structured tracking."""
        if self._cache is not None:
            cached = await self._cache.get(request)
            if cached is not None:
                _log.info(
                    "llm.completion.cache_hit",
                    model=request.model,
                    prompt_tokens=cached.usage.prompt_tokens,
                )
                return cached

        async def _call() -> CompletionResponse:
            return await self._backend.complete(request)

        response = await self._breaker.call(request.model, _call)

        _log.info(
            "llm.completion.success",
            model=request.model,
            latency_ms=response.latency_ms,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            cost_usd=response.cost_usd,
            finish_reason=response.finish_reason,
        )

        if self._cache is not None:
            await self._cache.set(request, response)
        return response

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        """Stream content chunks. No caching (streams aren't cached).

        Streaming bypasses the breaker by design — partial output is
        already in flight to the user when an error occurs, and
        retrying from the breaker would replay tokens out of order.
        """
        _log.info("llm.completion.stream_start", model=request.model)
        async for chunk in self._backend.stream(request):
            yield chunk


def _build_redis_cache_backend(redis_url: str) -> CacheBackend:
    """Lazily build a Redis-backed cache. Falls back to in-memory if redis lib missing."""
    try:
        import redis.asyncio as redis_async
    except ImportError:
        _log.warning("llm.cache.redis_unavailable_using_in_memory")
        return InMemoryCacheBackend()

    class _RedisCacheBackend:
        def __init__(self, url: str) -> None:
            self._client = redis_async.from_url(url, decode_responses=True)

        async def get(self, key: str) -> str | None:
            value = await self._client.get(key)
            return str(value) if value is not None else None

        async def set(self, key: str, value: str, *, ex: int) -> None:
            await self._client.set(key, value, ex=ex)

    return _RedisCacheBackend(redis_url)


__all__ = ["LLMClient"]
