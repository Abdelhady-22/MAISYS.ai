"""Tests for the shared scraper storage helpers (`scrapers._storage`)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scrapers._storage import GcsSink, ScraperManifest, parse_gs_uri, slugify


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


def test_parse_gs_uri() -> None:
    assert parse_gs_uri("gs://b/p") == ("b", "p")
    assert parse_gs_uri("gs://b") == ("b", "")
    with pytest.raises(ValueError):
        parse_gs_uri("s3://b/p")


def test_slugify() -> None:
    assert (
        slugify("https://www.mayoclinic.org/symptoms/cough/basics/x/sym-20050846") == "sym-20050846"
    )
    assert slugify("https://medlineplus.gov/ency/article/000123.htm") == "000123"
    assert slugify("https://medlineplus.gov/druginfo/meds/a682878.html") == "a682878"
    assert (
        slugify("https://medlineplus.gov/genetics/condition/cystic-fibrosis/") == "cystic-fibrosis"
    )


def test_gcssink_page_aggregate_manifest_roundtrip() -> None:
    client = FakeClient()
    sink = GcsSink(client, "gs://maisys-data-dev")

    assert sink.page_exists("raw/mayo_clinic", "symptoms", "sym-1") is False
    entry = sink.write_page("raw/mayo_clinic", "symptoms", "sym-1", {"url": "u1", "x": 1})
    assert entry.status == "scraped"
    assert entry.remote_uri == "gs://maisys-data-dev/raw/mayo_clinic/symptoms/sym-1.json"
    assert sink.page_exists("raw/mayo_clinic", "symptoms", "sym-1") is True

    sink.write_aggregate("raw/mayo_clinic", "symptoms", [{"url": "u1"}])
    assert sink.read_aggregate("raw/mayo_clinic", "symptoms") == [{"url": "u1"}]

    manifest = ScraperManifest(
        run_id="r1", area="mayo_clinic", sub_area="symptoms", started_at="t0", scraped_count=1
    )
    uri = sink.write_manifest("mayo_symptoms", manifest)
    assert uri == "gs://maisys-data-dev/manifests/mayo_symptoms.json"
    stored = json.loads(
        client.bucket("maisys-data-dev").store["manifests/mayo_symptoms.json"].decode()
    )
    assert stored["scraped_count"] == 1


def test_gcssink_respects_root_prefix() -> None:
    client = FakeClient()
    sink = GcsSink(client, "gs://bucket/nested/root")
    name = sink.page_object_name("raw/mayo_clinic", "symptoms", "sym-1")
    assert name == "nested/root/raw/mayo_clinic/symptoms/sym-1.json"
