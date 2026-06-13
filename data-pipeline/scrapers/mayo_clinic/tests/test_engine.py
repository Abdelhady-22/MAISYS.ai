"""Orchestration + I/O tests for the Mayo engine (no browser, no network).

A fake ``PageSource`` supplies canned URLs/sections and an in-memory Fake GCS
client captures uploads — same pattern as ``test_upload_local_to_gcs.py``.
"""

from __future__ import annotations

import json
from typing import Any

from scrapers.mayo_clinic._engine import AreaConfig, run_area_cli

OUTPUT = "gs://maisys-data-dev"

AREA = AreaConfig(
    sub_area="symptoms",
    base_url="https://www.mayoclinic.org",
    index_url="https://www.mayoclinic.org/symptoms/index?letter=",
    path_pattern=r"/symptoms/[^/]+/basics/",
)

URLS = [
    ("https://www.mayoclinic.org/symptoms/cough/basics/definition/sym-20050846", "Cough"),
    ("https://www.mayoclinic.org/symptoms/fever/basics/definition/sym-20050997", "Fever"),
]


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


# ── Fake PageSource ─────────────────────────────────────────────────────────
class FakePageSource:
    def __init__(
        self,
        urls: list[tuple[str, str]],
        *,
        fail_urls: set[str] | None = None,
    ) -> None:
        self.urls = urls
        self.fail_urls = fail_urls or set()
        self.scraped: list[str] = []
        self.closed = False

    async def collect_urls(self) -> list[tuple[str, str]]:
        return list(self.urls)

    async def scrape_page(self, url: str, name: str) -> tuple[str, dict[str, str], bool]:
        self.scraped.append(url)
        if url in self.fail_urls:
            return name, {}, False
        return name, {"Overview": f"{name} overview text"}, True

    async def aclose(self) -> None:
        self.closed = True


def run(
    client: FakeClient,
    source: FakePageSource,
    extra_argv: list[str] | None = None,
) -> int:
    argv = ["--output-bucket", OUTPUT, *(extra_argv or [])]
    return run_area_cli(AREA, argv, source_factory=lambda area, rps: source, client=client)


# ── Tests ────────────────────────────────────────────────────────────────────
def test_writes_pages_aggregate_and_manifest() -> None:
    client = FakeClient()
    source = FakePageSource(URLS)
    rc = run(client, source)
    assert rc == 0

    store = client.bucket("maisys-data-dev").store
    assert "raw/mayo_clinic/symptoms/sym-20050846.json" in store
    assert "raw/mayo_clinic/symptoms/sym-20050997.json" in store
    assert "raw/mayo_clinic/symptoms.json" in store
    assert "manifests/mayo_symptoms.json" in store

    page = json.loads(store["raw/mayo_clinic/symptoms/sym-20050846.json"].decode())
    assert page["status"] == "success"
    assert page["sections"] == {"Overview": "Cough overview text"}

    aggregate = json.loads(store["raw/mayo_clinic/symptoms.json"].decode())
    assert {r["name"] for r in aggregate} == {"Cough", "Fever"}

    manifest = json.loads(store["manifests/mayo_symptoms.json"].decode())
    assert manifest["scraped_count"] == 2
    assert manifest["failed_count"] == 0
    assert manifest["sub_area"] == "symptoms"
    assert manifest["aggregate_uri"].endswith("raw/mayo_clinic/symptoms.json")


def test_skip_if_exists() -> None:
    client = FakeClient()
    # Pre-seed the first page object → it must be skipped, not re-scraped.
    client.bucket("maisys-data-dev").store["raw/mayo_clinic/symptoms/sym-20050846.json"] = b"{}"
    source = FakePageSource(URLS)
    rc = run(client, source)
    assert rc == 0
    assert source.scraped == [URLS[1][0]]  # only the second URL scraped

    manifest = json.loads(
        client.bucket("maisys-data-dev").store["manifests/mayo_symptoms.json"].decode()
    )
    assert manifest["skipped_count"] == 1
    assert manifest["scraped_count"] == 1


def test_force_rescrapes_existing() -> None:
    client = FakeClient()
    client.bucket("maisys-data-dev").store["raw/mayo_clinic/symptoms/sym-20050846.json"] = b"{}"
    source = FakePageSource(URLS)
    rc = run(client, source, ["--force"])
    assert rc == 0
    assert set(source.scraped) == {u for u, _ in URLS}  # both re-scraped


def test_partial_failure_isolated_and_exit_one() -> None:
    client = FakeClient()
    source = FakePageSource(URLS, fail_urls={URLS[0][0]})
    rc = run(client, source)
    assert rc == 1  # a failure → exit 1

    store = client.bucket("maisys-data-dev").store
    # Failed page has no per-page object (so it retries next run); the good one does.
    assert "raw/mayo_clinic/symptoms/sym-20050846.json" not in store
    assert "raw/mayo_clinic/symptoms/sym-20050997.json" in store

    manifest = json.loads(store["manifests/mayo_symptoms.json"].decode())
    assert manifest["failed_count"] == 1
    assert manifest["scraped_count"] == 1
    assert manifest["failed_urls"] == [URLS[0][0]]


def test_dry_run_writes_nothing() -> None:
    client = FakeClient()
    source = FakePageSource(URLS)
    rc = run(client, source, ["--dry-run"])
    assert rc == 0
    assert source.scraped == []  # nothing scraped
    assert client.bucket("maisys-data-dev").store == {}  # nothing written


def test_max_pages_caps() -> None:
    client = FakeClient()
    source = FakePageSource(URLS)
    run(client, source, ["--max-pages", "1"])
    assert source.scraped == [URLS[0][0]]


def test_bad_uri_exit_two() -> None:
    client = FakeClient()
    source = FakePageSource(URLS)
    rc = run_area_cli(
        AREA, ["--output-bucket", "/local"], source_factory=lambda a, r: source, client=client
    )
    assert rc == 2
    assert source.closed is False  # never started


def test_source_closed_after_run() -> None:
    client = FakeClient()
    source = FakePageSource(URLS)
    run(client, source)
    assert source.closed is True
