"""Per-area link-extraction and parse tests + utils (proven logic)."""

from __future__ import annotations

from scrapers.medlineplus import _engine as eng
from scrapers.medlineplus import utils


def test_normalize_url_trailing_slash() -> None:
    assert utils.normalize_url("/genetics/condition/cystic-fibrosis") == (
        "https://medlineplus.gov/genetics/condition/cystic-fibrosis/"
    )
    assert utils.normalize_url("/lab-tests/glucose") == "https://medlineplus.gov/lab-tests/glucose/"
    assert utils.normalize_url("/diabetes.html") == "https://medlineplus.gov/diabetes.html"


def test_normalize_text_fixes_mojibake_and_whitespace() -> None:
    assert utils.normalize_text("hello\xa0world") == "hello world"
    assert utils.normalize_text("a   b\n\n\n c") == "a b\n\nc"


def test_extract_sections_skips_metadata_headings() -> None:
    html = """
    <div id="ency-content">
      <h2>Causes</h2><p>Real medical content here.</p>
      <h2>Review Date 1/1/2026</h2><p>ignore me</p>
      <h2>About MedlinePlus</h2><p>ignore me too</p>
    </div>
    """
    from bs4 import BeautifulSoup

    sections = utils.extract_sections(BeautifulSoup(html, "html.parser"))
    headings = {s["heading"] for s in sections}
    assert "Causes" in headings
    assert not any("Review Date" in h for h in headings)
    assert "About MedlinePlus" not in headings


def test_health_topics_links_filters() -> None:
    html = """
    <article>
      <li><a href="/diabetes.html">Diabetes</a></li>
      <li><a href="/ency/article/000123.htm">Ency leak</a></li>
      <li><a href="/druginfo/meds/a1.html">Drug leak</a></li>
      <li><a href="/asthma.html">Asthma</a></li>
    </article>
    """
    links = eng.health_topics_links(html, eng.HEALTH_TOPICS.index_urls[0])
    urls = {u for u, _ in links}
    assert urls == {
        "https://medlineplus.gov/diabetes.html",
        "https://medlineplus.gov/asthma.html",
    }


def test_health_topics_parse_summary_and_aliases() -> None:
    html = """
    <html><body>
      <h1>Diabetes</h1>
      <span class="alsocalled">Also called: High blood sugar, DM</span>
      <div id="topic-summary">
        <p>Diabetes is a disease where blood glucose is too high.</p>
        <h2>Types</h2><p>Type 1 and Type 2.</p>
      </div>
    </body></html>
    """
    rec = eng.health_topics_parse("https://medlineplus.gov/diabetes.html", "Diabetes", html)
    assert rec["type"] == "health_topic"
    assert "blood glucose is too high" in rec["summary"]
    assert rec["also_known_as"] == ["High blood sugar", "DM"]
    assert rec["sections"][0]["heading"] == "Types"


def test_drugs_links_and_parse_brand_names() -> None:
    index = """
    <ul id="index">
      <li><a href="/druginfo/meds/a682878.html">Acetaminophen</a></li>
      <li><a href="/druginfo/natural/1.html">Vitamin C</a></li>
      <li><a href="/about/x.html">nope</a></li>
    </ul>
    """
    links = eng.drugs_links(index, "https://medlineplus.gov/druginfo/drug_Aa.html")
    assert {u for u, _ in links} == {
        "https://medlineplus.gov/druginfo/meds/a682878.html",
        "https://medlineplus.gov/druginfo/natural/1.html",
    }

    detail = """
    <h1>Acetaminophen</h1>
    <div class="brandname">Tylenol, Panadol</div>
    <div id="ency-content"><h2>Why</h2><p>Pain relief.</p></div>
    """
    rec = eng.drugs_parse("https://medlineplus.gov/druginfo/meds/a682878.html", "x", detail)
    assert rec["type"] == "drug"
    assert rec["brand_names"] == ["Tylenol", "Panadol"]
    assert rec["sections"][0]["heading"] == "Why"


def test_encyclopedia_links_requires_6digit() -> None:
    html = """
    <li><a href="/ency/article/000123.htm">Anemia</a></li>
    <li><a href="/ency/imagepages/nope.htm">No id</a></li>
    """
    links = eng.encyclopedia_links(html, "https://medlineplus.gov/ency/encyclopedia_A.htm")
    assert links == [("https://medlineplus.gov/ency/article/000123.htm", "Anemia")]


def test_genetics_links_and_subtype_parse() -> None:
    cond_index = "https://medlineplus.gov/genetics/condition/"
    html = f"""
    <a href="{cond_index}">index self</a>
    <a href="/genetics/condition/cystic-fibrosis/">Cystic fibrosis</a>
    """
    links = eng.genetics_links(html, cond_index)
    assert links == [
        ("https://medlineplus.gov/genetics/condition/cystic-fibrosis/", "Cystic fibrosis")
    ]

    detail = (
        "<h1>Cystic fibrosis</h1>"
        "<div id='ency-content'><h2>Desc</h2><p>A genetic disorder.</p></div>"
    )
    rec = eng.genetics_parse(links[0][0], "Cystic fibrosis", detail)
    assert rec["type"] == "genetics_condition"
    assert rec["subtype"] == "condition"
