"""MedlinePlus shared scraping utilities (adapted from the proven staged scraper).

The content-cleaning selectors, section extraction, text normalization (mojibake
fixes), and URL canonicalization are preserved **verbatim** from
``_staging/MedlinePlus/utils.py``. Only the local-disk I/O, ``setup_logger``, the
``requests`` session/``safe_get`` (now injected at the engine layer), and
``random_delay`` were removed. Full type annotations were added for mypy.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

BASE_URL = "https://medlineplus.gov"

STRIP_SELECTORS = [
    "nav",
    "footer",
    "header",
    "#header",
    "#footer",
    "#nav",
    ".skip-nav",
    ".usa-banner",
    ".mp-breadcrumbs",
    ".breadcrumb",
    "#mplus-nav",
    "#mplus-footer",
    ".social-links",
    ".share-widget",
    ".return-top",
    "#mplus-disclaimer",
    ".side-box",
    ".menu",
    ".sidenav",
    "script",
    "style",
    "noscript",
    '[role="navigation"]',
    '[role="banner"]',
]

_SKIP_HEADING_PREFIXES = ("review date", "disclaimer", "disclaimers")
_SKIP_HEADING_EXACT = {
    "about medlineplus",
    "what's new",
    "site map",
    "customer support",
    "related information",
}

_FOOTER_SKIP = [
    "national library of medicine",
    "8600 rockville pike",
    "u.s. department of health",
    "subscribe to rss",
    "nlm web policies",
    "hhs vulnerability",
]


def normalize_text(text: str) -> str:
    """Fix encoding issues and normalize whitespace (NFKC + mojibake cleanup)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"Â([\x80-\xff])", r"\1", text)
    text = re.sub(r"Â(?=[\s\"'’”])", "", text)
    text = re.sub(r"Â\Z", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def clean_medlineplus_page(soup: Any) -> Any:
    """Remove navigation/footer/sidebar/boilerplate (in place)."""
    for selector in STRIP_SELECTORS:
        for el in soup.select(selector):
            el.decompose()
    return soup


def get_main_content(soup: Any) -> Any:
    """Find the narrowest main-content container on a MedlinePlus page."""
    return (
        soup.find("div", id="topic-summary")
        or soup.find("div", id="ency-content")
        or soup.find("div", id="share-content")
        or soup.find("div", class_="main-content")
        or soup.find("section", id="section-1")
        or soup.find("article")
        or soup.find("main")
        or soup.find("div", id="main")
    )


def extract_sections(soup: Any) -> list[dict[str, str]]:
    """Parse the main content area into ``[{heading, content}, ...]``."""
    clean_medlineplus_page(soup)
    main = get_main_content(soup) or soup

    sections: list[dict[str, str]] = []
    current_heading: str | None = None
    current_content: list[str] = []

    def flush() -> None:
        nonlocal current_heading, current_content
        if current_heading is not None:
            text = normalize_text("\n".join(current_content))
            if text:
                sections.append({"heading": normalize_text(current_heading), "content": text})
        current_content = []

    seen_lists: set[int] = set()
    for tag in main.find_all(["h2", "h3", "p", "ul", "ol", "table"]):
        if tag.name in ("h2", "h3"):
            flush()
            heading_text = tag.get_text(strip=True)
            heading_lc = heading_text.lower()
            if heading_lc in _SKIP_HEADING_EXACT:
                current_heading = None
                continue
            if any(heading_lc.startswith(p) for p in _SKIP_HEADING_PREFIXES):
                current_heading = None
                continue
            current_heading = heading_text
            continue

        if tag.name in ("ul", "ol"):
            if any(id(p) in seen_lists for p in tag.parents):
                continue
            seen_lists.add(id(tag))
            items = [li.get_text(" ", strip=True) for li in tag.find_all("li", recursive=False)]
            bullets = [f"• {it}" for it in items if it and len(it) > 1]
            if bullets:
                current_content.append("\n".join(bullets))
            continue

        txt = tag.get_text(" ", strip=True)
        if txt and len(txt) > 2:
            if any(skip in txt.lower() for skip in _FOOTER_SKIP):
                continue
            current_content.append(txt)

    flush()
    return sections


def normalize_url(url: str) -> str:
    """Normalize a URL to absolute canonical form (trailing slash where the
    live site 301s to it: genetics conditions/genes and lab tests)."""
    url = url.strip()
    if url.startswith("/"):
        url = BASE_URL + url
    url = url.rstrip("/")
    if re.search(r"/(genetics/(condition|gene)|lab-tests)/[^/?#]+$", url):
        url += "/"
    return url
