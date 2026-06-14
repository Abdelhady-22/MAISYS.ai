"""KV cache for LLM completion responses, backed by Redis.

Cache key is SHA-256 over the canonical JSON form of:
``(model, messages, temperature, max_tokens, response_format, tools)``.
Cache value is the JSON-serialised ``CompletionResponse``.

Default TTL is one hour; callers can override per-request via
``ttl_seconds``. A ``CacheBackend`` protocol lets tests swap the
Redis dependency for an in-memory dict.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any, Protocol, runtime_checkable

from shared.llm_client.types import CompletionRequest, CompletionResponse, Usage
from shared.logger import get_logger

_log = get_logger(__name__)

DEFAULT_TTL_SECONDS = 3600


@runtime_checkable
class CacheBackend(Protocol):
    """Minimal async KV protocol — Redis fits, in-memory dict for tests fits."""

    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, *, ex: int) -> None: ...


def cache_key(request: CompletionRequest) -> str:
    """Compute the SHA-256 cache key for ``request``.

    Streaming and metadata are excluded — they don't change the
    semantic content of the response.
    """
    canonical: dict[str, Any] = {
        "model": request.model,
        "messages": [
            {"role": m.role, "content": m.content, "name": m.name} for m in request.messages
        ],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "response_format": request.response_format,
        "tools": list(request.tools) if request.tools else None,
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return "llm:cache:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class InMemoryCacheBackend:
    """Process-local cache, used by tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        # ex is honoured by Redis; this fake stores without expiry
        self._store[key] = value


class LLMCache:
    """High-level cache facade that serialises completion responses."""

    def __init__(self, backend: CacheBackend, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._backend = backend
        self._ttl = ttl_seconds

    async def get(self, request: CompletionRequest) -> CompletionResponse | None:
        key = cache_key(request)
        raw = await self._backend.get(key)
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return CompletionResponse(
                content=data["content"],
                model=data["model"],
                usage=Usage(**data["usage"]),
                latency_ms=data["latency_ms"],
                cached=True,
                finish_reason=data.get("finish_reason"),
                tool_calls=tuple(data["tool_calls"]) if data.get("tool_calls") else None,
                cost_usd=data.get("cost_usd"),
            )
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            _log.warning("llm.cache.deserialise_failed", error=str(e))
            return None

    async def set(
        self,
        request: CompletionRequest,
        response: CompletionResponse,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        key = cache_key(request)
        payload = json.dumps(
            {
                "content": response.content,
                "model": response.model,
                "usage": asdict(response.usage),
                "latency_ms": response.latency_ms,
                "finish_reason": response.finish_reason,
                "tool_calls": list(response.tool_calls) if response.tool_calls else None,
                "cost_usd": response.cost_usd,
            }
        )
        await self._backend.set(key, payload, ex=ttl_seconds or self._ttl)


__all__ = ["CacheBackend", "InMemoryCacheBackend", "LLMCache", "cache_key"]
