"""Tests for WebSearchAgent."""

from __future__ import annotations

import asyncio
import time

import pytest

from services.drug_service.agents.web_search import (
    WebFetchResult,
    WebFetcherProtocol,
    WebSearchAgent,
)
from services.drug_service.models.schemas import Language


class FakeFetcher(WebFetcherProtocol):
    def __init__(
        self,
        results: dict[tuple[str, str], WebFetchResult | None] | None = None,
        raise_on: bool = False,
    ) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, str, Language]] = []
        self.raise_on = raise_on

    async def fetch_interaction(
        self, drug_a: str, drug_b: str, language: Language
    ) -> WebFetchResult | None:
        self.calls.append((drug_a, drug_b, language))
        if self.raise_on:
            raise RuntimeError("network failure")
        return self.results.get((drug_a, drug_b))


@pytest.mark.asyncio
async def test_returns_description_and_url() -> None:
    fetcher = FakeFetcher(
        {
            ("aspirin", "warfarin"): WebFetchResult(
                text="Bleeding risk increased", url="https://drugs.com/x"
            )
        }
    )
    agent = WebSearchAgent(fetcher=fetcher, rate_limit_seconds=0.0)
    result = await agent.find_interaction("aspirin", "warfarin", "en")
    assert result is not None
    description, url = result
    assert "Bleeding" in description
    assert url == "https://drugs.com/x"


@pytest.mark.asyncio
async def test_none_when_no_result() -> None:
    fetcher = FakeFetcher({})
    agent = WebSearchAgent(fetcher=fetcher, rate_limit_seconds=0.0)
    result = await agent.find_interaction("aspirin", "ibuprofen", "en")
    assert result is None


@pytest.mark.asyncio
async def test_swallows_fetcher_errors_returns_none() -> None:
    """Best-effort fallback — exceptions become None, callers proceed."""
    fetcher = FakeFetcher(raise_on=True)
    agent = WebSearchAgent(fetcher=fetcher, rate_limit_seconds=0.0)
    result = await agent.find_interaction("aspirin", "warfarin", "en")
    assert result is None


@pytest.mark.asyncio
async def test_rate_limit_enforces_minimum_interval() -> None:
    fetcher = FakeFetcher(
        {
            ("a", "b"): WebFetchResult(text="text", url="url"),
            ("c", "d"): WebFetchResult(text="text", url="url"),
        }
    )
    agent = WebSearchAgent(fetcher=fetcher, rate_limit_seconds=0.1)
    start = time.monotonic()
    await agent.find_interaction("a", "b", "en")
    await agent.find_interaction("c", "d", "en")
    elapsed = time.monotonic() - start
    # At least one rate-limit interval between the two calls
    assert elapsed >= 0.1


@pytest.mark.asyncio
async def test_concurrent_calls_serialise_via_rate_limit() -> None:
    """Two concurrent calls don't fire simultaneously — the second waits."""
    fetcher = FakeFetcher(
        {(f"a{i}", f"b{i}"): WebFetchResult(text="text", url=f"url{i}") for i in range(3)}
    )
    agent = WebSearchAgent(fetcher=fetcher, rate_limit_seconds=0.05)
    start = time.monotonic()
    await asyncio.gather(
        agent.find_interaction("a0", "b0", "en"),
        agent.find_interaction("a1", "b1", "en"),
        agent.find_interaction("a2", "b2", "en"),
    )
    elapsed = time.monotonic() - start
    # 3 calls with 0.05s rate limit → at least 2 intervals = 0.10s
    assert elapsed >= 0.10
