"""Tests for the preserved Mayo parsing/cleaning logic."""

from __future__ import annotations

from scrapers.mayo_clinic import utils


def test_extract_links_from_index_filters_and_dedupes() -> None:
    html = """
    <html><body>
      <a href="/symptoms/cough/basics/definition/sym-1">Cough</a>
      <a href="/symptoms/cough/basics/definition/sym-1">Cough dup</a>
      <a href="/symptoms/fever/basics/definition/sym-2">Fever</a>
      <a href="/about/contact">About</a>
    </body></html>
    """
    links = utils.extract_links_from_index(
        html, "https://www.mayoclinic.org", r"/symptoms/[^/]+/basics/"
    )
    urls = {u for u, _ in links}
    assert urls == {
        "https://www.mayoclinic.org/symptoms/cough/basics/definition/sym-1",
        "https://www.mayoclinic.org/symptoms/fever/basics/definition/sym-2",
    }


def test_clean_article_text_strips_boilerplate() -> None:
    html = """
    <html><body>
      <nav>site nav</nav>
      <div id="main-content">
        <h2>Overview</h2>
        <p>Cough is a reflex that clears the throat.</p>
        <p>From Mayo Clinic to your inbox</p>
        <p>Thank you for subscribing!</p>
      </div>
      <footer>footer junk</footer>
    </body></html>
    """
    text = utils.clean_article_text(html)
    assert "Cough is a reflex" in text
    assert "From Mayo Clinic to your inbox" not in text
    assert "Thank you for subscribing" not in text
    assert "site nav" not in text


def test_extract_drug_content_sections() -> None:
    html = """
    <html><body><article>
      <h1>Acetaminophen</h1>
      <h2>Description</h2><p>A pain reliever.</p>
      <h2>Precautions</h2><p>Do not exceed the dose.</p>
    </article></body></html>
    """
    data = utils.extract_drug_content(html)
    assert data["drug_name"] == "Acetaminophen"
    assert data["sections"]["Description"] == "A pain reliever."
    assert data["sections"]["Precautions"] == "Do not exceed the dose."
