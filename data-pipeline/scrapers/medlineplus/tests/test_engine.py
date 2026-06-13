"""Orchestration + I/O tests for the MedlinePlus engine (no network)."""

from __future__ import annotations

import json
from typing import Any

from scrapers.medlineplus import _engine as eng

OUTPUT = "gs://maisys-data-dev"
INDEX = "https://medlineplus.gov/lab-tests/"
GLUCOSE = "https://medlineplus.gov/lab-tests/glucose/"
CHOL = "https://medlineplus.gov/lab-tests/cholesterol/"

INDEX_HTML = """
<html><body><article>
  <a href="/lab-tests/glucose/">Glucose Test</a>
  <a href="/lab-tests/cholesterol/">Cholesterol Test</a>
  <a href="/about/contact">About</a>
</article></body></html>
"""


def _detail(title: str) -> str:
    return f"""
    <html><body>
      <h1>{title}</h1>
      <div id="ency-content">
        <h2>What is it</h2><p>{title} measures something useful in blood.</p>
      </div>
    </body></html>
    """


FETCH = {INDEX: INDEX_HTML, GLUCOSE: _detail("Glucose"), CHOL: _detail("Cholesterol")}


# ── Fake GCS ───────────────────────────────────────────────────────────────
class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str) -> None:
        self._bucket = bucket
        self.name = name

    def exists(self) -> bool:
        return self.name in self._bucket.store

    def upload_from_string(self, data: Any, content_type: str | None = None) -> None:
        self._bucket.store[self.name] = data.encode("utf-8") if isinstance(data, str) else data

    def download_as_text(self) -> str:
        return self._bucket.store[self.name].decode("utf-8")


class FakeBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self.store: dict[str, bytes] = {}

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


class FakeClient:
    def __init__(self) -> None:
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name: str) -> FakeBucket:
        return self.buckets.setdefault(name, FakeBucket(name))


def make_fetch(fetched: list[str] | None = None, fail: set[str] | None = None) -> eng.FetchFn:
    fail = fail or set()

    def _fetch(url: str) -> str | None:
        if fetched is not None:
            fetched.append(url)
        if url in fail:
            return None
        return FETCH.get(url)

    return _fetch


def run(client: FakeClient, fetch: eng.FetchFn, extra: list[str] | None = None) -> int:
    argv = ["--output-bucket", OUTPUT, *(extra or [])]
    return eng.run_area_cli(eng.LAB_TESTS, argv, fetch_factory=lambda rps: fetch, client=client)


# ── Tests ────────────────────────────────────────────────────────────────────
def test_writes_pages_aggregate_manifest() -> None:
    client = FakeClient()
    rc = run(client, make_fetch())
    assert rc == 0
    store = client.bucket("maisys-data-dev").store
    assert "raw/medlineplus/lab_tests/glucose.json" in store
    assert "raw/medlineplus/lab_tests/cholesterol.json" in store
    assert "raw/medlineplus/lab_tests.json" in store
    assert "manifests/medlineplus_lab_tests.json" in store

    page = json.loads(store["raw/medlineplus/lab_tests/glucose.json"].decode())
    assert page["type"] == "lab_test"
    assert page["name"] == "Glucose"
    assert page["sections"][0]["heading"] == "What is it"

    manifest = json.loads(store["manifests/medlineplus_lab_tests.json"].decode())
    assert manifest["scraped_count"] == 2
    assert manifest["failed_count"] == 0


def test_skip_if_exists() -> None:
    client = FakeClient()
    client.bucket("maisys-data-dev").store["raw/medlineplus/lab_tests/glucose.json"] = b"{}"
    fetched: list[str] = []
    run(client, make_fetch(fetched))
    # Index fetched + only cholesterol detail fetched (glucose skipped).
    assert GLUCOSE not in fetched
    assert CHOL in fetched
    manifest = json.loads(
        client.bucket("maisys-data-dev").store["manifests/medlineplus_lab_tests.json"].decode()
    )
    assert manifest["skipped_count"] == 1
    assert manifest["scraped_count"] == 1


def test_force_rescrapes() -> None:
    client = FakeClient()
    client.bucket("maisys-data-dev").store["raw/medlineplus/lab_tests/glucose.json"] = b"{}"
    fetched: list[str] = []
    run(client, make_fetch(fetched), ["--force"])
    assert GLUCOSE in fetched and CHOL in fetched


def test_partial_failure_exit_one() -> None:
    client = FakeClient()
    rc = run(client, make_fetch(fail={GLUCOSE}))
    assert rc == 1
    store = client.bucket("maisys-data-dev").store
    assert "raw/medlineplus/lab_tests/glucose.json" not in store
    assert "raw/medlineplus/lab_tests/cholesterol.json" in store
    manifest = json.loads(store["manifests/medlineplus_lab_tests.json"].decode())
    assert manifest["failed_count"] == 1
    assert manifest["scraped_count"] == 1


def test_dry_run_writes_nothing() -> None:
    client = FakeClient()
    fetched: list[str] = []
    rc = run(client, make_fetch(fetched), ["--dry-run"])
    assert rc == 0
    # Index is fetched (to list URLs) but no detail pages, no uploads.
    assert GLUCOSE not in fetched and CHOL not in fetched
    assert client.bucket("maisys-data-dev").store == {}


def test_max_pages() -> None:
    client = FakeClient()
    fetched: list[str] = []
    run(client, make_fetch(fetched), ["--max-pages", "1"])
    assert GLUCOSE in fetched and CHOL not in fetched


def test_bad_uri_exit_two() -> None:
    client = FakeClient()
    rc = eng.run_area_cli(
        eng.LAB_TESTS,
        ["--output-bucket", "/x"],
        fetch_factory=lambda rps: make_fetch(),
        client=client,
    )
    assert rc == 2
