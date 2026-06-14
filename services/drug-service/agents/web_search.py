"""Web Search agent — Playwright-backed fallback for missing interaction data.

Conforms to the ``WebSearchAgentLike`` protocol that
``InteractionAgent`` depends on. Production deploys use Playwright
against drugs.com (with DailyMed as a backup); tests inject a
``WebFetcherProtocol`` fake so the test suite has no browser
dependency.

Rate limiting: at most 1 request per second per host, enforced via
an asyncio ``Semaphore`` + monotonic-clock gating. Always cites the
source URL.

Network failures and parse errors are swallowed — this is a
best-effort fallback. The agent returns ``None`` rather than raising
so the caller (InteractionAgent) can record the absence and proceed.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import quote_plus

from services.drug_service.exceptions import WebSearchException
from services.drug_service.models.schemas import Language
from shared.logger import get_logger

_log = get_logger(__name__)

DEFAULT_RATE_LIMIT_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class WebFetchResult:
    """One web search hit — text content + URL the content came from."""

    text: str
    url: str


class WebFetcherProtocol(Protocol):
    """What WebSearchAgent needs from a fetcher backend."""

    async def fetch_interaction(
        self, drug_a: str, drug_b: str, language: Language
    ) -> WebFetchResult | None: ...


class PlaywrightWebFetcher(WebFetcherProtocol):
    """Production fetcher — Playwright on drugs.com with DailyMed backup.

    Playwright is imported lazily so this module is importable in
    environments without it (CI sandboxes, type-check-only runs).
    """

    def __init__(
        self, *, headless: bool = True, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self._headless = headless
        self._timeout = timeout_seconds

    async def fetch_interaction(
        self, drug_a: str, drug_b: str, language: Language
    ) -> WebFetchResult | None:
        # Lazy import — keeps Playwright off the import path in tests.
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise WebSearchException("Playwright is not installed") from exc

        primary_url = (
            f"https://www.drugs.com/interactions-check.php?"
            f"drug_list={quote_plus(drug_a)},{quote_plus(drug_b)}"
        )
        backup_url = (
            f"https://dailymed.nlm.nih.gov/dailymed/search.cfm?"
            f"query={quote_plus(drug_a)}+{quote_plus(drug_b)}"
        )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=self._headless)
            try:
                # Try primary first; on any failure or empty result, try backup.
                for url in (primary_url, backup_url):
                    page = await browser.new_page()
                    try:
                        await page.goto(url, timeout=int(self._timeout * 1000))
                        # Selector heuristic — drugs.com puts interaction prose
                        # in `.interactions-reference-wrapper`; DailyMed shows
                        # raw label content. Take whatever text the page yields
                        # and let the LLM downstream interpret it.
                        text = await page.evaluate("() => document.body.innerText")
                        if text and len(text.strip()) > 100:
                            return WebFetchResult(text=text.strip()[:4000], url=url)
                    except Exception as exc:
                        _log.info("web_search.page_failed", url=url, error=str(exc))
                    finally:
                        await page.close()
            finally:
                await browser.close()
        return None


class WebSearchAgent:
    """Implements the ``WebSearchAgentLike`` protocol.

    Note: this is NOT a ``BaseAgent`` subclass — it doesn't go through
    ``execute()`` because callers (other agents) handle their own
    progress events and latency tracking. Keeping it lean makes
    composition simpler.
    """

    def __init__(
        self,
        *,
        fetcher: WebFetcherProtocol,
        rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
    ) -> None:
        self._fetcher = fetcher
        self._rate_limit = rate_limit_seconds
        self._lock = asyncio.Lock()
        self._last_call_monotonic: float = 0.0

    async def find_interaction(
        self, drug_a: str, drug_b: str, language: Language
    ) -> tuple[str, str] | None:
        """Best-effort web lookup. Returns (description, url) or None."""
        await self._respect_rate_limit()
        try:
            result = await self._fetcher.fetch_interaction(drug_a, drug_b, language)
        except WebSearchException as exc:
            _log.warning("web_search.fetch_failed", drug_a=drug_a, drug_b=drug_b, error=str(exc))
            return None
        except Exception as exc:
            _log.warning(
                "web_search.unexpected_error", drug_a=drug_a, drug_b=drug_b, error=str(exc)
            )
            return None

        if result is None:
            return None
        return (result.text, result.url)

    async def _respect_rate_limit(self) -> None:
        """Block until ``rate_limit_seconds`` have elapsed since last call."""
        async with self._lock:
            now = time.monotonic()
            delta = now - self._last_call_monotonic
            if delta < self._rate_limit:
                await asyncio.sleep(self._rate_limit - delta)
            self._last_call_monotonic = time.monotonic()


__all__ = [
    "PlaywrightWebFetcher",
    "WebFetchResult",
    "WebFetcherProtocol",
    "WebSearchAgent",
]
