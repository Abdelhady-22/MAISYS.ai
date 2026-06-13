"""Generic orchestration engine shared by the four Mayo sub-area scrapers.

The scraping flow (A-Z index collection → per-URL scrape → write) is identical
across sub-areas; only the ``AreaConfig`` (URLs, path pattern, extractor) differs.
The browser-backed work is hidden behind the ``PageSource`` protocol so tests can
inject a fake and exercise the full I/O + orchestration without Playwright.
"""

from __future__ import annotations

import argparse
import asyncio
import string
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from google.cloud import storage

from .._logging import configure_logging, get_logger
from .._storage import GcsSink, ScraperManifest, parse_gs_uri, slugify
from . import utils

log = get_logger()

RAW_SUBDIR = "raw/mayo_clinic"
MANIFEST_PREFIX = "mayo"

Extractor = Literal["tabs", "drug"]


@dataclass
class AreaConfig:
    """Per-sub-area configuration."""

    sub_area: str
    base_url: str
    index_url: str  # letter is appended (A-Z index)
    path_pattern: str
    extractor: Extractor = "tabs"
    index_letters: str = field(default=string.ascii_uppercase)


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class PageSource(Protocol):
    """The browser-facing seam: collect index URLs and scrape one page."""

    async def collect_urls(self) -> list[tuple[str, str]]: ...

    async def scrape_page(self, url: str, name: str) -> tuple[str, dict[str, str], bool]:
        """Return ``(resolved_name, sections, ok)`` for one page."""
        ...

    async def aclose(self) -> None: ...


# ──────────────────────────────────────────────────────────────────────────
# Default Playwright-backed source (lazy import; never touched by tests)
# ──────────────────────────────────────────────────────────────────────────
class BrowserPageSource:
    """Default ``PageSource`` using the proven Playwright + stealth scraper."""

    def __init__(self, area: AreaConfig, *, rate_limit_rps: float) -> None:
        self.area = area
        self.interval = 1.0 / rate_limit_rps if rate_limit_rps > 0 else 0.0
        self._pw_ctx: Any = None
        self._browser: Any = None
        self._page: Any = None

    async def _ensure_page(self) -> Any:
        if self._page is None:
            from playwright.async_api import async_playwright

            self._pw_ctx = async_playwright()
            pw = await self._pw_ctx.__aenter__()
            self._browser, _, self._page = await utils.setup_browser(pw)
        return self._page

    async def _delay(self) -> None:
        if self.interval:
            await asyncio.sleep(self.interval)

    async def collect_urls(self) -> list[tuple[str, str]]:
        page = await self._ensure_page()
        collected: list[tuple[str, str]] = []
        for letter in self.area.index_letters:
            index_url = self.area.index_url + letter
            if not await utils.safe_navigate(page, index_url, log):
                continue
            html = await page.content()
            found = utils.extract_links_from_index(html, self.area.base_url, self.area.path_pattern)
            collected.extend(found)
            log.info("index_letter", letter=letter, found=len(found), total=len(collected))
            await self._delay()
        return collected

    async def scrape_page(self, url: str, name: str) -> tuple[str, dict[str, str], bool]:
        page = await self._ensure_page()
        ok = await utils.safe_navigate(page, url, log)
        await self._delay()
        if not ok:
            return name, {}, False
        if self.area.extractor == "drug":
            html = await page.content()
            data = utils.extract_drug_content(html)
            sections: dict[str, str] = data["sections"]
            return (data["drug_name"] or name), sections, bool(sections)
        sections = await utils.get_tab_content(page, log)
        return name, sections, bool(sections)

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw_ctx is not None:
            await self._pw_ctx.__aexit__(None, None, None)


SourceFactory = Any  # Callable[[AreaConfig, float], PageSource]


def _default_source_factory(area: AreaConfig, rate_limit_rps: float) -> PageSource:
    return BrowserPageSource(area, rate_limit_rps=rate_limit_rps)


# ──────────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────────
def _dedupe(urls: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for url, name in urls:
        if url not in seen:
            seen.add(url)
            out.append((url, name))
    return out


async def scrape_area(
    area: AreaConfig,
    source: PageSource,
    sink: GcsSink,
    *,
    max_pages: int | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> ScraperManifest:
    """Run one sub-area end to end and return its manifest."""
    manifest = ScraperManifest(
        run_id=str(uuid.uuid4()),
        area="mayo_clinic",
        sub_area=area.sub_area,
        started_at=_utc_now_iso(),
    )
    try:
        urls = _dedupe(await source.collect_urls())
        if max_pages is not None:
            urls = urls[:max_pages]
        log.info("urls_collected", sub_area=area.sub_area, count=len(urls))

        existing = sink.read_aggregate(RAW_SUBDIR, area.sub_area) or []
        existing_by_url = {r["url"]: r for r in existing if isinstance(r, dict) and "url" in r}
        records: list[dict[str, Any]] = []

        for url, name in urls:
            manifest.urls.append(url)
            slug = slugify(url)

            if not force and sink.page_exists(RAW_SUBDIR, area.sub_area, slug):
                manifest.skipped_count += 1
                if url in existing_by_url:
                    records.append(existing_by_url[url])
                continue

            if dry_run:
                log.info("plan_scrape", url=url, slug=slug)
                continue

            resolved_name, sections, ok = await source.scrape_page(url, name)
            success = ok and bool(sections)
            record: dict[str, Any] = {
                "name": resolved_name or name,
                "url": url,
                "status": "success" if success else "error",
                "sections": sections,
                "scraped_at": _utc_now_iso(),
            }
            records.append(record)
            if success:
                entry = sink.write_page(RAW_SUBDIR, area.sub_area, slug, record)
                manifest.scraped_count += 1
                manifest.total_bytes += entry.size_bytes
            else:
                manifest.failed_count += 1
                manifest.failed_urls.append(url)

        if not dry_run:
            manifest.aggregate_uri = sink.write_aggregate(RAW_SUBDIR, area.sub_area, records)
            manifest.completed_at = _utc_now_iso()
            sink.write_manifest(f"{MANIFEST_PREFIX}_{area.sub_area}", manifest)
    finally:
        await source.aclose()

    return manifest


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def build_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Scrape a Mayo Clinic sub-area to GCS.")
    parser.add_argument("--output-bucket", required=True, help="Root GCS gs:// URI.")
    parser.add_argument(
        "--rate-limit-rps", type=float, default=0.5, help="Requests per second (default 0.5)."
    )
    parser.add_argument("--max-pages", type=int, default=None, help="Cap pages scraped (testing).")
    parser.add_argument(
        "--resume", action="store_true", default=True, help="Skip already-scraped pages (default)."
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-scrape even if the page object exists."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="List planned URLs without scraping/uploading."
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging.")
    return parser


def run_area_cli(
    area: AreaConfig,
    argv: list[str] | None = None,
    *,
    source_factory: SourceFactory | None = None,
    client: Any = None,
) -> int:
    """CLI entrypoint for one sub-area. Returns the process exit code."""
    parser = build_parser(f"mayo_{area.sub_area}")
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    try:
        parse_gs_uri(args.output_bucket)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.rate_limit_rps < 0:
        print("Error: --rate-limit-rps must be >= 0", file=sys.stderr)
        return 2

    gcs_client = client if client is not None else storage.Client()
    sink = GcsSink(gcs_client, args.output_bucket)
    factory = source_factory or _default_source_factory
    source: PageSource = factory(area, args.rate_limit_rps)

    manifest = asyncio.run(
        scrape_area(
            area, source, sink, max_pages=args.max_pages, force=args.force, dry_run=args.dry_run
        )
    )

    label = "DRY RUN" if args.dry_run else "RUN"
    print(
        f"\n=== Mayo {area.sub_area} {label} (run_id={manifest.run_id}) ===\n"
        f"  scraped={manifest.scraped_count} skipped={manifest.skipped_count} "
        f"failed={manifest.failed_count} bytes={manifest.total_bytes}"
    )
    return 1 if manifest.failed_count else 0
