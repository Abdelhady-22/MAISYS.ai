"""Cache repository tests — keying, set/get, in-memory store."""

from __future__ import annotations

import pytest

from services.translation_service.repository.cache_repo import (
    InMemoryTranslationCache,
    make_cache_key,
)


def test_cache_key_deterministic() -> None:
    k1 = make_cache_key(
        text="Hello",
        source_lang="en",
        target_lang="ar",
        mode="google",
        style="general",
    )
    k2 = make_cache_key(
        text="Hello",
        source_lang="en",
        target_lang="ar",
        mode="google",
        style="general",
    )
    assert k1 == k2
    assert k1.startswith("translation:")
    assert len(k1) == len("translation:") + 64  # SHA-256 hex


def test_cache_key_changes_with_text() -> None:
    k1 = make_cache_key(
        text="Hello",
        source_lang="en",
        target_lang="ar",
        mode="google",
        style="general",
    )
    k2 = make_cache_key(
        text="World",
        source_lang="en",
        target_lang="ar",
        mode="google",
        style="general",
    )
    assert k1 != k2


def test_cache_key_changes_with_direction() -> None:
    k1 = make_cache_key(
        text="Hello",
        source_lang="en",
        target_lang="ar",
        mode="google",
        style="general",
    )
    k2 = make_cache_key(
        text="Hello",
        source_lang="ar",
        target_lang="en",
        mode="google",
        style="general",
    )
    assert k1 != k2


def test_cache_key_changes_with_mode() -> None:
    k1 = make_cache_key(
        text="Hello",
        source_lang="en",
        target_lang="ar",
        mode="google",
        style="general",
    )
    k2 = make_cache_key(
        text="Hello",
        source_lang="en",
        target_lang="ar",
        mode="llm",
        style="general",
    )
    assert k1 != k2


def test_cache_key_changes_with_style() -> None:
    k1 = make_cache_key(
        text="Hello",
        source_lang="en",
        target_lang="ar",
        mode="llm",
        style="general",
    )
    k2 = make_cache_key(
        text="Hello",
        source_lang="en",
        target_lang="ar",
        mode="llm",
        style="clinical",
    )
    assert k1 != k2


@pytest.mark.asyncio
async def test_in_memory_set_get() -> None:
    cache = InMemoryTranslationCache()
    assert await cache.get("nonexistent") is None

    await cache.set("k1", "v1")
    assert await cache.get("k1") == "v1"

    await cache.set("k1", "v2")  # overwrite
    assert await cache.get("k1") == "v2"
