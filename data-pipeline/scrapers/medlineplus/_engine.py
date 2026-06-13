"""Generic orchestration engine shared by the five MedlinePlus sub-area scrapers.

Each area provides its index URL(s), a link-extraction function, and a
detail-parse function (ported from the proven staged scrapers). The HTTP fetch
is injected (``FetchFn``) so tests run without network; the default fetcher uses
``requests`` with an honest educational User-Agent, robots.txt respect, and
429 backoff (MedlinePlus is fine with a declared bot).
"""

from __future__ import annotations

import argparse
import re
import string
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from google.cloud import storage

from .._logging import configure_logging, get_logger
from .._storage import GcsSink, ScraperManifest, parse_gs_uri, slugify
from . import utils

log = get_logger()

RAW_SUBDIR = "raw/medlineplus"
MANIFEST_PREFIX = "medlineplus"
USER_AGENT = "MAISYS-EducationalScraper/1.0 (https://github.com/Abdelhady-22/MAISYS.ai)"

FetchFn = Callable[[str], "str | None"]
LinksFn = Callable[[str, str], "list[tuple[str, str]]"]
ParseFn = Callable[[str, str, str], "dict[str, Any]"]


@dataclass
class MplusArea:
    sub_area: str
    index_urls: list[str]
    links_fn: LinksFn
    parse_fn: ParseFn


# ──────────────────────────────────────────────────────────────────────────
# Default polite fetcher (requests; never used by tests)
# ──────────────────────────────────────────────────────────────────────────
class DefaultFetcher:
    """``requests``-based fetch with honest UA, robots.txt, rate limit, 429 backoff."""

    def __init__(self, *, rate_limit_rps: float, max_retries: int = 3) -> None:
        import requests

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        self.interval = 1.0 / rate_limit_rps if rate_limit_rps > 0 else 0.0
        self.max_retries = max_retries
        self._robots: dict[str, RobotFileParser] = {}
        self._consecutive_429 = 0

    def _allowed(self, url: str) -> bool:
        from urllib.parse import urlsplit

        parts = urlsplit(url)
        host = f"{parts.scheme}://{parts.netloc}"
        rp = self._robots.get(host)
        if rp is None:
            rp = RobotFileParser()
            rp.set_url(f"{host}/robots.txt")
            try:
                rp.read()
            except Exception as exc:  # noqa: BLE001 - robots unreachable -> allow
                log.warning("robots_unreadable", host=host, error=str(exc))
            self._robots[host] = rp
        return rp.can_fetch(USER_AGENT, url)

    def __call__(self, url: str) -> str | None:
        if not self._allowed(url):
            log.warning("robots_disallow", url=url)
            return None
        if self.interval:
            time.sleep(self.interval)
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=30)
                if resp.status_code == 429:
                    self._consecutive_429 += 1
                    if self._consecutive_429 >= 3:
                        raise RuntimeError("aborting: 3 consecutive 429 responses")
                    time.sleep(2**attempt)
                    continue
                self._consecutive_429 = 0
                resp.raise_for_status()
                text: str = resp.text
                return text
            except Exception as exc:  # noqa: BLE001 - retried
                log.warning("fetch_error", url=url, attempt=attempt, error=str(exc))
                time.sleep(2**attempt)
        log.error("fetch_failed", url=url, retries=self.max_retries)
        return None


def _default_fetch_factory(rate_limit_rps: float) -> FetchFn:
    return DefaultFetcher(rate_limit_rps=rate_limit_rps)


# ──────────────────────────────────────────────────────────────────────────
# Orchestration
# ──────────────────────────────────────────────────────────────────────────
def scrape_area(
    area: MplusArea,
    sink: GcsSink,
    *,
    fetch_fn: FetchFn,
    max_pages: int | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> ScraperManifest:
    """Run one MedlinePlus sub-area end to end and return its manifest."""
    manifest = ScraperManifest(
        run_id=str(uuid.uuid4()),
        area="medlineplus",
        sub_area=area.sub_area,
        started_at=utils.now_iso(),
    )

    # Collect detail URLs from every index page.
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index_url in area.index_urls:
        html = fetch_fn(index_url)
        if not html:
            continue
        for url, name in area.links_fn(html, index_url):
            if url not in seen:
                seen.add(url)
                links.append((url, name))
    if max_pages is not None:
        links = links[:max_pages]
    log.info("urls_collected", sub_area=area.sub_area, count=len(links))

    existing = sink.read_aggregate(RAW_SUBDIR, area.sub_area) or []
    existing_by_url = {r["url"]: r for r in existing if isinstance(r, dict) and "url" in r}
    records: list[dict[str, Any]] = []

    for url, name in links:
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

        html = fetch_fn(url)
        record: dict[str, Any]
        if html is None:
            record = {"name": name, "url": url, "sections": [], "scraped_at": utils.now_iso()}
            success = False
        else:
            record = area.parse_fn(url, name, html)
            success = bool(record.get("sections"))

        record["status"] = "success" if success else "error"
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
        manifest.completed_at = utils.now_iso()
        sink.write_manifest(f"{MANIFEST_PREFIX}_{area.sub_area}", manifest)

    return manifest


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def build_parser(prog: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description="Scrape a MedlinePlus sub-area to GCS.")
    parser.add_argument("--output-bucket", required=True, help="Root GCS gs:// URI.")
    parser.add_argument("--rate-limit-rps", type=float, default=0.5, help="Requests/sec (0.5).")
    parser.add_argument("--max-pages", type=int, default=None, help="Cap pages (testing).")
    parser.add_argument(
        "--resume", action="store_true", default=True, help="Skip existing (default)."
    )
    parser.add_argument("--force", action="store_true", help="Re-scrape existing pages.")
    parser.add_argument("--dry-run", action="store_true", help="List URLs without scraping.")
    parser.add_argument("--verbose", action="store_true", help="Debug logging.")
    return parser


def run_area_cli(
    area: MplusArea,
    argv: list[str] | None = None,
    *,
    fetch_factory: Callable[[float], FetchFn] | None = None,
    client: Any = None,
) -> int:
    """CLI entrypoint for one MedlinePlus sub-area."""
    args = build_parser(f"medlineplus_{area.sub_area}").parse_args(argv)
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
    factory = fetch_factory or _default_fetch_factory
    fetch_fn = factory(args.rate_limit_rps)

    manifest = scrape_area(
        area,
        sink,
        fetch_fn=fetch_fn,
        max_pages=args.max_pages,
        force=args.force,
        dry_run=args.dry_run,
    )

    label = "DRY RUN" if args.dry_run else "RUN"
    print(
        f"\n=== MedlinePlus {area.sub_area} {label} (run_id={manifest.run_id}) ===\n"
        f"  scraped={manifest.scraped_count} skipped={manifest.skipped_count} "
        f"failed={manifest.failed_count} bytes={manifest.total_bytes}"
    )
    return 1 if manifest.failed_count else 0


# ──────────────────────────────────────────────────────────────────────────
# Per-area link extraction + detail parsing (ported from staged scrapers)
# ──────────────────────────────────────────────────────────────────────────
def _h1_name(soup: Any, fallback: str) -> str:
    h1 = soup.find("h1")
    return utils.normalize_text(h1.get_text(strip=True)) if h1 else fallback


# -- health topics ----------------------------------------------------------
_HT_SKIP = (
    "/druginfo/",
    "/ency/",
    "/genetics/",
    "/lab-tests/",
    "/about/",
    "/xml/",
    "/spanish/",
    "/all_healthtopics",
    "/healthtopics.html",
    "/druginformation.html",
    "/encyclopedia.html",
    "/sitemap.html",
    "/whatsnew/",
    "/images/",
    "/css/",
    "/uswds/",
    "/jslib/",
    "support.nlm.nih.gov",
)


def _is_topic_url(url: str) -> bool:
    if "medlineplus.gov" not in url:
        return False
    if any(skip in url for skip in _HT_SKIP):
        return False
    return url.endswith(".html")


def health_topics_links(html: str, index_url: str) -> list[tuple[str, str]]:
    soup: Any = BeautifulSoup(html, "html.parser")
    article = soup.find("article") or soup
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for li in article.select("li"):
        a = li.find("a", href=True)
        if not a:
            continue
        text = a.get_text(strip=True)
        if not text:
            continue
        url = utils.normalize_url(urljoin(index_url, a["href"]))
        if _is_topic_url(url) and url not in seen:
            seen.add(url)
            out.append((url, text))
    return out


def _aliases_from_page(soup: Any) -> list[str]:
    label_el = soup.select_one("span.alsocalled")
    if label_el is None:
        for el in soup.find_all(["p", "div", "span"]):
            if el.get_text(" ", strip=True).lower().startswith("also called"):
                label_el = el
                break
    if label_el is None:
        return []
    label = re.sub(
        r"^\s*also\s+called\s*:?\s*",
        "",
        label_el.get_text(" ", strip=True),
        flags=re.IGNORECASE,
    )
    return [a.strip() for a in label.split(",") if a.strip()]


def health_topics_parse(url: str, name: str, html: str) -> dict[str, Any]:
    soup: Any = BeautifulSoup(html, "html.parser")
    utils.clean_medlineplus_page(soup)
    page_name = _h1_name(soup, name)
    summary = ""
    summary_div = soup.find("div", id="topic-summary")
    if summary_div:
        summary = utils.normalize_text(summary_div.get_text(" ", strip=True))
    sections = utils.extract_sections(BeautifulSoup(html, "html.parser"))
    return {
        "type": "health_topic",
        "name": page_name,
        "url": url,
        "also_known_as": _aliases_from_page(soup),
        "summary": summary,
        "sections": sections,
        "scraped_at": utils.now_iso(),
    }


# -- generic section-only parser (lab tests, encyclopedia) ------------------
def _section_parse(record_type: str) -> ParseFn:
    def parse(url: str, name: str, html: str) -> dict[str, Any]:
        soup: Any = BeautifulSoup(html, "html.parser")
        page_name = _h1_name(soup, name)
        sections = utils.extract_sections(BeautifulSoup(html, "html.parser"))
        return {
            "type": record_type,
            "name": page_name,
            "url": url,
            "sections": sections,
            "scraped_at": utils.now_iso(),
        }

    return parse


# -- drugs ------------------------------------------------------------------
def _is_drug_url(url: str) -> bool:
    return "/druginfo/meds/" in url or "/druginfo/natural/" in url


def drugs_links(html: str, index_url: str) -> list[tuple[str, str]]:
    soup: Any = BeautifulSoup(html, "html.parser")
    index_ul = soup.find("ul", id="index") or soup.find("article") or soup
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for li in index_ul.find_all("li"):
        for a in li.find_all("a", href=True):
            url = utils.normalize_url(urljoin(index_url, a["href"]))
            if _is_drug_url(url) and url not in seen:
                seen.add(url)
                out.append((url, a.get_text(strip=True)))
    return out


def drugs_parse(url: str, name: str, html: str) -> dict[str, Any]:
    soup: Any = BeautifulSoup(html, "html.parser")
    page_name = _h1_name(soup, name)
    brand_names: list[str] = []
    brand_div = soup.find("div", class_=re.compile(r"brand|trade", re.IGNORECASE))
    if brand_div:
        brand_names = [b.strip() for b in brand_div.get_text(",").split(",") if b.strip()]
    sections = utils.extract_sections(BeautifulSoup(html, "html.parser"))
    return {
        "type": "drug",
        "name": page_name,
        "url": url,
        "brand_names": brand_names,
        "sections": sections,
        "scraped_at": utils.now_iso(),
    }


# -- lab tests --------------------------------------------------------------
def _is_lab_test_url(url: str) -> bool:
    if "/lab-tests/" not in url or "medlineplus.gov" not in url:
        return False
    parts = url.split("#")[0].split("/lab-tests/")
    return len(parts) >= 2 and bool(parts[1].strip("/"))


def lab_tests_links(html: str, index_url: str) -> list[tuple[str, str]]:
    soup: Any = BeautifulSoup(html, "html.parser")
    article = soup.find("article") or soup
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in article.find_all("a", href=True):
        name = a.get_text(strip=True)
        if not name:
            continue
        url = utils.normalize_url(urljoin(index_url, a["href"]))
        if _is_lab_test_url(url) and url not in seen:
            seen.add(url)
            out.append((url, name))
    return out


# -- encyclopedia -----------------------------------------------------------
def encyclopedia_links(html: str, index_url: str) -> list[tuple[str, str]]:
    soup: Any = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for li in soup.find_all("li"):
        a = li.find("a", href=True)
        if not a:
            continue
        href = a["href"]
        title = a.get_text(strip=True)
        if re.search(r"\d{6}", href) and title:
            url = utils.normalize_url(href if href.startswith("http") else urljoin(index_url, href))
            if url not in seen:
                seen.add(url)
                out.append((url, title))
    return out


# -- genetics ---------------------------------------------------------------
def genetics_links(html: str, index_url: str) -> list[tuple[str, str]]:
    soup: Any = BeautifulSoup(html, "html.parser")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        title = a.get_text(strip=True)
        if not title or not re.search(r"/genetics/(condition|gene)/", href):
            continue
        url = utils.normalize_url(href if href.startswith("http") else urljoin(index_url, href))
        if url.rstrip("/") == index_url.rstrip("/"):
            continue
        if url not in seen:
            seen.add(url)
            out.append((url, title))
    return out


def genetics_parse(url: str, name: str, html: str) -> dict[str, Any]:
    subtype = "gene" if "/genetics/gene/" in url else "condition"
    soup: Any = BeautifulSoup(html, "html.parser")
    page_name = _h1_name(soup, name)
    sections = utils.extract_sections(BeautifulSoup(html, "html.parser"))
    return {
        "type": f"genetics_{subtype}",
        "name": page_name,
        "url": url,
        "subtype": subtype,
        "sections": sections,
        "scraped_at": utils.now_iso(),
    }


# ──────────────────────────────────────────────────────────────────────────
# Area definitions
# ──────────────────────────────────────────────────────────────────────────
def _drug_index_urls() -> list[str]:
    base = "https://medlineplus.gov/druginfo/drug_"
    return [f"{base}{c}a.html" for c in string.ascii_uppercase] + [f"{base}00.html"]


def _ency_index_urls() -> list[str]:
    base = "https://medlineplus.gov/ency/encyclopedia_"
    return [f"{base}{c}.htm" for c in string.ascii_uppercase] + [f"{base}0-9.htm"]


HEALTH_TOPICS = MplusArea(
    sub_area="health_topics",
    index_urls=["https://medlineplus.gov/all_healthtopics.html"],
    links_fn=health_topics_links,
    parse_fn=health_topics_parse,
)
DRUGS = MplusArea(
    sub_area="drugs",
    index_urls=_drug_index_urls(),
    links_fn=drugs_links,
    parse_fn=drugs_parse,
)
LAB_TESTS = MplusArea(
    sub_area="lab_tests",
    index_urls=["https://medlineplus.gov/lab-tests/"],
    links_fn=lab_tests_links,
    parse_fn=_section_parse("lab_test"),
)
ENCYCLOPEDIA = MplusArea(
    sub_area="encyclopedia",
    index_urls=_ency_index_urls(),
    links_fn=encyclopedia_links,
    parse_fn=_section_parse("encyclopedia"),
)
GENETICS = MplusArea(
    sub_area="genetics",
    index_urls=[
        "https://medlineplus.gov/genetics/condition/",
        "https://medlineplus.gov/genetics/gene/",
    ],
    links_fn=genetics_links,
    parse_fn=genetics_parse,
)
