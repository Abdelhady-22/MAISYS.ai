"""Translation cache — Redis-backed with an in-memory test fallback.

Per Part 1 §7.7 the cache key is SHA-256 of source text + language
pair, TTL 24 hours. We extend the key to also include ``mode`` and
``style`` — translations from different modes can vary materially
(LLM vs. Google), so caching them under the same key would mask
intentional mode selection.

The Protocol lets tests inject ``InMemoryTranslationCache`` without
needing a real Redis container. Production uses ``RedisTranslationCache``
wrapping ``redis.asyncio``.
"""

from __future__ import annotations

import hashlib
from typing import Protocol

DEFAULT_TTL_SECONDS = 86_400  # 24 hours per Part 1 §7.7


def make_cache_key(
    *,
    text: str,
    source_lang: str,
    target_lang: str,
    mode: str,
    style: str,
) -> str:
    """Build the cache key for a translation request.

    Returns a SHA-256 hex digest prefixed with ``translation:`` so
    operators can clearly identify the keys in Redis.
    """
    raw = f"{source_lang}|{target_lang}|{mode}|{style}|{text}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"translation:{digest}"


class TranslationCache(Protocol):
    """Cache interface — Protocol so tests can inject in-memory."""

    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None: ...


# ─── In-memory cache (for tests) ─────────────────────────────────


class InMemoryTranslationCache:
    """Pure-Python cache. NOT for production — no TTL eviction."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,  # noqa: ARG002 — tests don't expire
    ) -> None:
        self._store[key] = value


# ─── Redis cache (production) ────────────────────────────────────


class RedisTranslationCache:
    """``redis.asyncio``-backed cache. Lazy import so tests don't need Redis."""

    def __init__(self, *, redis_url: str) -> None:
        self._redis_url = redis_url
        self._client: object | None = None

    async def _get_client(self) -> object:
        if self._client is None:
            from redis.asyncio import Redis

            self._client = Redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def get(self, key: str) -> str | None:
        client = await self._get_client()
        value = await client.get(key)  # type: ignore[attr-defined]
        if value is None:
            return None
        return str(value)

    async def set(
        self,
        key: str,
        value: str,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        client = await self._get_client()
        await client.set(key, value, ex=ttl_seconds)  # type: ignore[attr-defined]


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "InMemoryTranslationCache",
    "RedisTranslationCache",
    "TranslationCache",
    "make_cache_key",
]
