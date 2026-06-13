"""Mayo Clinic shared scraping utilities (adapted from the proven staged scraper).

The Playwright/stealth browser automation, content-cleaning selectors, and the
40+ boilerplate-removal regexes are preserved **verbatim** from the original
``_staging/mayo-clinic/utils.py`` — this is proven anti-bot/cleaning logic and is
not rewritten. Only the local-disk I/O (``save_json``/``load_checkpoint``),
``setup_logger``, and ``print_stats`` were removed (replaced by ``GcsSink`` and
structlog at the engine layer). Full type annotations were added for mypy.

Playwright and playwright-stealth are imported lazily inside ``setup_browser`` so
this module imports cleanly (and tests run) without a browser installed.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

# ============================================================================
# CONFIGURATION (verbatim from the staged scraper)
# ============================================================================

MAX_RETRIES = 3
NAV_TIMEOUT = 30_000  # ms
CONTENT_TIMEOUT = 10_000  # ms

HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    # Match the UA below — Akamai cross-checks these.
    "sec-ch-ua": '"Not)A;Brand";v="99", "Google Chrome";v="138", "Chromium";v="138"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

# CSS classes / IDs / tags to strip from extracted content
STRIP_SELECTORS = [
    "nav",
    "footer",
    "header.site-header",
    ".social-sharing",
    ".related-articles",
    ".sidebar",
    ".ad-container",
    ".breadcrumb",
    ".nav",
    ".menu",
    ".footer",
    ".site-header",
    ".search-bar",
    "#global-nav",
    "#site-footer",
    "#breadcrumb",
    '[role="navigation"]',
    '[role="banner"]',
    ".content-within__nav",
    ".recipe-callout",
    ".cta-banner",
    ".request-appointment",
    ".myc-subscription-form",
    ".myc-subscription-step-wrapper",
    ".newsletter-signup",
    ".email-signup",
    ".content-within__cta",
    ".mayo-content-link",
    'form[action*="newsletter" i]',
    'form[action*="subscribe" i]',
    'form[id*="newsletter" i]',
    'form[id*="subscribe" i]',
    "script",
    "style",
    "noscript",
]

_BOILERPLATE_PATTERNS = [
    r"There is a problem with information submitted for this request[^.]*\.",
    r"Review/update the information highlighted below and resubmit the form\.",
    r"From Mayo Clinic to your inbox",
    r"Sign up for free and stay up to date on research advancements[^.]*\.",
    r"Click here for an email preview\.?",
    r"Error Email field is required\.?",
    r"Error Include a valid email address\.?",
    r"Thank you for subscribing!?",
    r"You'?ll soon start receiving the latest Mayo Clinic[^.]*\.",
    r"Sorry something went wrong with your subscription\.?",
    r"Please,? try again in a couple of minutes\.?",
    r"We use the data you provide to deliver you[^.]*\.",
    r"To provide you with the most relevant and helpful information[^.]*\.",
    r"If you are a Mayo Clinic patient, this could include[^.]*\.",
    r"If you are a Mayo Clinic patient,\s*we will only use your protected health information[^.]*\.",  # noqa: E501
    r"You may opt out of email communications at any time by clicking on[^.]*?(?=\n\n|\n[A-Z]|$)",
    r"unsubscribe link in the e-?mail\.?",
    r"Women'?s health topics[^.]*subscribe below\.?",
    r"Request an appointment",
    r"Mayo Clinic does not endorse[^.]*\.",
    r"©\s*\d{4}\s*Mayo Foundation[^\n]*",
    r"Advertising & Sponsorship[^\n]*",
    r"Check out these best-sellers[^\n]*",
]
_BOILERPLATE_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _BOILERPLATE_PATTERNS]


# ============================================================================
# CONTENT CLEANING (verbatim logic, annotated)
# ============================================================================
def clean_article_text(html: str) -> str:
    """Extract clean article body text from a Mayo Clinic page."""
    soup: Any = BeautifulSoup(html, "html.parser")

    for selector in STRIP_SELECTORS:
        for el in soup.select(selector):
            el.decompose()

    content = (
        soup.find("div", id="main-content")
        or soup.find("article")
        or soup.find("main")
        or soup.find("div", class_=re.compile(r"content(?!-within__nav)"))
    )

    if not content:
        return ""

    paragraphs: list[str] = []
    seen_lists: set[int] = set()

    for tag in content.find_all(["h1", "h2", "h3", "h4", "p", "ul", "ol", "td"]):
        if tag.name in ("ul", "ol"):
            if any(id(p) in seen_lists for p in tag.parents):
                continue
            seen_lists.add(id(tag))
            items = [li.get_text(" ", strip=True) for li in tag.find_all("li", recursive=False)]
            bullets = [f"• {it}" for it in items if it and len(it) > 1]
            if bullets:
                paragraphs.append("\n".join(bullets))
            continue

        text = tag.get_text(" ", strip=True)
        if text and len(text) > 2:
            paragraphs.append(text)

    result = "\n".join(paragraphs)
    for pattern in _BOILERPLATE_RE:
        result = pattern.sub("", result)
    result = _strip_mayo_noise(result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


# ----------------------------------------------------------------------------
# Cosmetic noise removal (verbatim regexes)
# ----------------------------------------------------------------------------
_NOISE_HEADINGS = (
    r"Products?\s+(?:and|&)\s+Services"
    r"|See\s+also"
    r"|Related(?:\s+(?:Articles?|Topics?|Information))?"
    r"|More\s+Information"
    r"|News\s+from\s+Mayo\s+Clinic"
    r"|Mayo\s+Clinic\s+Press"
    r"|Show\s+references?"
    r"|Show\s+more\s+related\s+content"
    r"|Associated\s+Procedures"
)
_NOISE_SECTION_RE = re.compile(
    rf"(?ms)^\s*(?:{_NOISE_HEADINGS})\s*$" r"(?:\s*\n[ \t]*[•\-\*][^\n]*)*" r"\s*\n?"
)
_TAIL_TRUNCATE_RE = re.compile(
    r"(?ms)^\s*("
    r"Mayo\s+Clinic\s+Connect"
    r"|Connect\s+with\s+others"
    r"|Living\s+with\s+[A-Za-z][\w\s\'\-]+\?"
    r"|Mayo\s+Clinic\s+in\s+(?:Rochester|Phoenix|Jacksonville|Arizona|Florida|Minnesota)"
    r"|[A-Z][\w\s\'\-,()]{2,80}care at Mayo Clinic"
    r").*\Z"
)
_BREADCRUMB_TAIL_RE = re.compile(
    r"(?ms)"
    r"(?:\n[•\-\*\s]*[^\n]{1,80}\n)?"
    r"[•\-\*\s]*[A-Z][\w\s\-,()/&\']{2,120}"
    r"\s*-\s*(?:Symptoms\s*&\s*causes|Diagnosis\s*&\s*treatment|Mayo\s+Clinic)"
    r".*\Z"
)
_TAB_NAV_TAIL_RE = re.compile(
    r"(?ms)\n[^\n]{1,120}\n[ \t]*[•\-\*][ \t]*About\b[ \t]*\n"
    r"[ \t]*[•\-\*][ \t]*(?:Doctors|Tests|Departments|Symptoms)"
    r".*\Z"
)
_PAGE_CODE_TAIL_RE = re.compile(r"(?ms)\n[\s•]*(?:CON|DRG|PAC|SYC|HRT|DG)-\d{5,}\s*\Z")
_PAGE_CODE_ANY_RE = re.compile(r"\s*(?:CON|DRG|PAC|SYC|HRT|DG)-\d{5,}\b")
_LINE_STRIP_RE = re.compile(
    r"(?im)^[\s•​]*("
    r"Share|Tweet|Print"
    r"|\d+\s+Replies?"
    r"|Discussions?"
    r"|Request\s+Appointment"
    r")\s*$\n?"
)
_EMPTY_BULLET_RE = re.compile(r"(?m)^[ \t]*[•\-\*][ \t​​]*$\n?")


def _strip_mayo_noise(text: str) -> str:
    """Remove cosmetic non-medical noise without altering surrounding prose."""
    if not text:
        return text

    text = text.replace("​", "").replace("​", "")
    text = _NOISE_SECTION_RE.sub("\n", text)
    text = _TAIL_TRUNCATE_RE.sub("", text)
    text = _PAGE_CODE_TAIL_RE.sub("", text)
    text = _PAGE_CODE_ANY_RE.sub("", text)
    text = _TAB_NAV_TAIL_RE.sub("", text)
    text = _BREADCRUMB_TAIL_RE.sub("", text)
    text = _LINE_STRIP_RE.sub("", text)
    text = _EMPTY_BULLET_RE.sub("", text)
    text = re.sub(r"(?m)^(.{1,80})\n\1\s*$", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def extract_structured_sections(html: str) -> list[dict[str, str]]:
    """Parse HTML into ``[{heading, content}, ...]`` using h2/h3 headings."""
    soup: Any = BeautifulSoup(html, "html.parser")

    for selector in STRIP_SELECTORS:
        for el in soup.select(selector):
            el.decompose()

    content = (
        soup.find("div", id="main-content") or soup.find("article") or soup.find("main") or soup
    )

    sections: list[dict[str, str]] = []
    current_heading: str | None = None
    current_content: list[str] = []

    def flush() -> None:
        nonlocal current_heading, current_content
        if current_heading is not None:
            text = " ".join(current_content).strip()
            if text:
                sections.append({"heading": current_heading, "content": text})
        current_content = []

    seen_lists: set[int] = set()
    for tag in content.find_all(["h2", "h3", "p", "ul", "ol", "table"]):
        if tag.name in ("h2", "h3"):
            flush()
            current_heading = tag.get_text(strip=True)
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
            current_content.append(txt)

    flush()
    for s in sections:
        for pattern in _BOILERPLATE_RE:
            s["content"] = pattern.sub("", s["content"])
        s["content"] = _strip_mayo_noise(s["content"])
        s["content"] = re.sub(r"\s{2,}", " ", s["content"]).strip()
    return [s for s in sections if s["content"]]


def extract_drug_content(html: str) -> dict[str, Any]:
    """Extract ``{drug_name, sections}`` from a Mayo drug page (no tabs)."""
    soup: Any = BeautifulSoup(html, "html.parser")

    for selector in STRIP_SELECTORS:
        for el in soup.select(selector):
            el.decompose()

    content = (
        soup.find("article") or soup.find("div", class_="content") or soup.find("main") or soup
    )

    h1 = content.find("h1") or soup.find("h1")
    drug_name = h1.get_text(strip=True) if h1 else ""

    sections: dict[str, str] = {}
    current_heading: str | None = None
    current_parts: list[str] = []

    def flush() -> None:
        nonlocal current_heading, current_parts
        if current_heading:
            text = " ".join(current_parts).strip()
            if text:
                sections[current_heading] = text
        current_parts = []

    seen_lists: set[int] = set()
    for tag in content.find_all(["h2", "h3", "p", "ul", "ol"]):
        if tag.name in ("h2", "h3"):
            flush()
            current_heading = tag.get_text(strip=True)
            continue

        if tag.name in ("ul", "ol"):
            if any(id(p) in seen_lists for p in tag.parents):
                continue
            seen_lists.add(id(tag))

        txt = tag.get_text(" ", strip=True)
        if txt and len(txt) > 2:
            current_parts.append(txt)
    flush()

    for k in list(sections.keys()):
        v = sections[k]
        for pat in _BOILERPLATE_RE:
            v = pat.sub("", v)
        v = _strip_mayo_noise(v)
        v = re.sub(r"\s{2,}", " ", v).strip()
        sections[k] = v
    sections = {k: v for k, v in sections.items() if v}

    return {"drug_name": drug_name, "sections": sections}


def extract_links_from_index(html: str, base_url: str, path_pattern: str) -> list[tuple[str, str]]:
    """Parse an index page; return deduped, sorted ``[(url, name), ...]``."""
    soup: Any = BeautifulSoup(html, "html.parser")
    seen: set[str] = set()
    results: list[tuple[str, str]] = []

    for a in soup.find_all("a", href=True):
        href = a["href"]
        name = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()

        if not name or not re.search(path_pattern, href):
            continue

        if href.startswith("/"):
            full_url = base_url.rstrip("/") + href
        elif href.startswith("http"):
            full_url = href
        else:
            continue

        full_url = full_url.rstrip("/")
        if full_url not in seen:
            seen.add(full_url)
            results.append((full_url, name))

    return sorted(results, key=lambda x: x[1].lower())


# ============================================================================
# BROWSER AUTOMATION (Playwright + stealth, lazy-imported)
# ============================================================================
async def setup_browser(playwright: Any) -> tuple[Any, Any, Any]:
    """Launch a stealth Chromium browser; return ``(browser, context, page)``."""
    browser = await playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = await browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=USER_AGENT,
        locale="en-US",
        timezone_id="America/Chicago",
        extra_http_headers=HEADERS,
    )
    page = await context.new_page()

    try:
        from playwright_stealth import stealth_async

        await stealth_async(page)
    except ImportError:
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            """)

    return browser, context, page


async def safe_navigate(page: Any, url: str, log: Any) -> bool:
    """Navigate to *url* with retries; return True on success."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT)
            if resp and resp.status == 200:
                await page.wait_for_timeout(2000)
                return True
            if resp and resp.status == 403:
                log.warning("nav_403", url=url, attempt=attempt)
                await page.wait_for_timeout(5000 * attempt)
            else:
                status = resp.status if resp else "no response"
                log.warning("nav_bad_status", url=url, status=status, attempt=attempt)
                await page.wait_for_timeout(2000 * attempt)
        except Exception as exc:  # noqa: BLE001 - retried
            log.warning("nav_error", url=url, attempt=attempt, error=str(exc))
            await page.wait_for_timeout(3000 * attempt)

    log.error("nav_failed", url=url, retries=MAX_RETRIES)
    return False


async def get_tab_content(page: Any, log: Any) -> dict[str, str]:
    """Detect and click through ALL tabs; return ``{tab_name: clean_text}``."""
    sections: dict[str, str] = {}

    tab_selectors = [
        "li.content-within__tab a",
        'a[role="tab"]',
        ".tabs__tab a",
        ".content-within__nav a",
    ]
    tabs_found: list[Any] = []
    for selector in tab_selectors:
        tabs_found = await page.query_selector_all(selector)
        if tabs_found:
            break

    if not tabs_found:
        html = await page.content()
        text = clean_article_text(html)
        if text:
            sections["Content"] = text
        return sections

    active_panel_selectors = [
        ".content-within__tab-panel.active",
        ".content-within__tab-panel.is-active",
        '.content-within__tab-panel[aria-hidden="false"]',
        '[role="tabpanel"]:not([hidden])',
        '[role="tabpanel"].active',
        ".tab-panel.active",
        "article",
    ]

    async def _active_panel_html() -> str:
        for sel in active_panel_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    html = await el.inner_html()
                    if html and html.strip():
                        result: str = html
                        return result
            except Exception:  # noqa: BLE001 - try next selector
                continue
        page_html: str = await page.content()
        return page_html

    for tab in tabs_found:
        tab_name = (await tab.inner_text()).strip()
        if not tab_name:
            continue
        try:
            await tab.click()
            await page.wait_for_timeout(1500)
            panel_html = await _active_panel_html()
            text = clean_article_text(panel_html)
            if text and tab_name not in sections:
                sections[tab_name] = text
        except Exception as exc:  # noqa: BLE001 - skip failed tab
            log.warning("tab_click_failed", tab=tab_name, error=str(exc))
            continue

    return sections
