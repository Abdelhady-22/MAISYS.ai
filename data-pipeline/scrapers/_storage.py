"""Cloud I/O layer shared by all scrapers.

Provides ``gs://`` URI parsing, a URL→slug helper, Pydantic manifest models, and
``GcsSink`` — a thin wrapper over ``google.cloud.storage`` that uploads JSON,
checks existence (idempotency), and reads back objects (resume). Only uses
``bucket()/blob()/exists()/upload_from_string()/download_as_text()`` so the
in-memory ``FakeClient`` used in tests works unchanged.

The "Both" storage model (per project decision): each scraped record is written
both as a per-page object (``<raw_subdir>/<sub_area>/<slug>.json``, enabling
per-URL skip-if-exists) and folded into an aggregated ``<raw_subdir>/<sub_area>.json``
(matching DATA_PLAN §4.2 for downstream ingesters).
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field

PageStatus = Literal["scraped", "skipped", "failed"]


def parse_gs_uri(uri: str) -> tuple[str, str]:
    """Split ``gs://bucket/prefix`` into ``(bucket, prefix)`` (prefix may be empty)."""
    if not uri.startswith("gs://"):
        raise ValueError(f"not a gs:// URI: {uri!r}")
    without_scheme = uri[len("gs://") :]
    bucket, _, prefix = without_scheme.partition("/")
    if not bucket:
        raise ValueError(f"gs:// URI must include a bucket: {uri!r}")
    return bucket, prefix.strip("/")


def slugify(url: str) -> str:
    """Derive a stable, GCS-safe slug from a page URL.

    Uses the last path segment (sans ``.html``/``.htm``), which for the target
    sources is a unique page code (Mayo ``syc-…``/``drg-…``, MedlinePlus
    ``000123``/``a682878``) or a stable topic slug.
    """
    path = urlsplit(url).path.strip("/")
    last = path.rsplit("/", 1)[-1] or path or "index"
    last = re.sub(r"\.html?$", "", last, flags=re.IGNORECASE)
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", last).strip("-.").lower()
    return slug or "index"


def compute_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


# ──────────────────────────────────────────────────────────────────────────
# Manifest models
# ──────────────────────────────────────────────────────────────────────────
class PageEntry(BaseModel):
    url: str
    slug: str
    remote_uri: str
    md5: str
    size_bytes: int
    status: PageStatus


class ScraperManifest(BaseModel):
    run_id: str
    area: str
    sub_area: str = ""
    started_at: str
    completed_at: str | None = None
    scraped_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    total_bytes: int = 0
    aggregate_uri: str = ""
    urls: list[str] = Field(default_factory=list)
    failed_urls: list[str] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# Sink
# ──────────────────────────────────────────────────────────────────────────
class GcsSink:
    """Generic JSON sink over a GCS bucket rooted at an ``--output-bucket`` URI."""

    def __init__(self, client: Any, output_uri: str) -> None:
        self.client = client
        self.bucket_name, self.root_prefix = parse_gs_uri(output_uri)
        self.bucket = client.bucket(self.bucket_name)

    def join(self, *parts: str) -> str:
        """Join the root prefix with ``parts`` into an object name."""
        segments = [self.root_prefix, *parts]
        return "/".join(s.strip("/") for s in segments if s)

    def uri_for(self, object_name: str) -> str:
        return f"gs://{self.bucket_name}/{object_name}"

    def exists(self, object_name: str) -> bool:
        return bool(self.bucket.blob(object_name).exists())

    def read_json(self, object_name: str) -> Any | None:
        blob = self.bucket.blob(object_name)
        if not blob.exists():
            return None
        try:
            return json.loads(blob.download_as_text())
        except Exception:  # noqa: BLE001 - corrupt object -> treat as absent
            return None

    def write_json(self, object_name: str, payload: Any) -> tuple[str, int, str]:
        """Upload ``payload`` as pretty JSON; return ``(uri, size_bytes, md5_hex)``."""
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.bucket.blob(object_name).upload_from_string(data, content_type="application/json")
        return self.uri_for(object_name), len(data), compute_md5(data)

    # -- per-page / aggregate / manifest helpers ---------------------------
    def page_object_name(self, raw_subdir: str, sub_area: str, slug: str) -> str:
        return self.join(raw_subdir, sub_area, f"{slug}.json")

    def aggregate_object_name(self, raw_subdir: str, sub_area: str) -> str:
        return self.join(raw_subdir, f"{sub_area}.json")

    def manifest_object_name(self, manifest_name: str) -> str:
        return self.join("manifests", f"{manifest_name}.json")

    def page_exists(self, raw_subdir: str, sub_area: str, slug: str) -> bool:
        return self.exists(self.page_object_name(raw_subdir, sub_area, slug))

    def write_page(self, raw_subdir: str, sub_area: str, slug: str, record: Any) -> PageEntry:
        object_name = self.page_object_name(raw_subdir, sub_area, slug)
        uri, size, md5 = self.write_json(object_name, record)
        url = record.get("url", "") if isinstance(record, dict) else ""
        return PageEntry(
            url=url, slug=slug, remote_uri=uri, md5=md5, size_bytes=size, status="scraped"
        )

    def write_aggregate(self, raw_subdir: str, sub_area: str, records: list[Any]) -> str:
        object_name = self.aggregate_object_name(raw_subdir, sub_area)
        uri, _, _ = self.write_json(object_name, records)
        return uri

    def read_aggregate(self, raw_subdir: str, sub_area: str) -> list[Any] | None:
        data = self.read_json(self.aggregate_object_name(raw_subdir, sub_area))
        return data if isinstance(data, list) else None

    def write_manifest(self, manifest_name: str, manifest: ScraperManifest) -> str:
        object_name = self.manifest_object_name(manifest_name)
        uri, _, _ = self.write_json(object_name, manifest.model_dump())
        return uri
