"""Tests for ``upload_local_to_gcs``.

GCS is never contacted: a small in-memory fake (:class:`FakeBucket` /
:class:`FakeBlob` / :class:`FakeClient`) stands in for the
``google.cloud.storage`` client. This keeps the suite hermetic, per the
data-pipeline rule that tests must not depend on a live external service.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from cloud.upload_local_to_gcs import (
    FileCountError,
    GcsUploader,
    Md5MismatchError,
    OptionsConfig,
    SourceConfig,
    TargetConfig,
    UploadConfig,
    check_file_count,
    compute_md5,
    enumerate_files,
    load_config,
    main,
    parse_gs_uri,
    remote_object_name,
)


# ──────────────────────────────────────────────────────────────────────────
# In-memory GCS fake
# ──────────────────────────────────────────────────────────────────────────
def _b64_md5(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode("ascii")


class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str) -> None:
        self._bucket = bucket
        self.name = name
        self.storage_class: str | None = None
        self.chunk_size: int | None = None

    def exists(self) -> bool:
        return self.name in self._bucket.store

    def reload(self) -> None:
        if self.name not in self._bucket.store:
            raise KeyError(self.name)

    @property
    def md5_hash(self) -> str | None:
        data = self._bucket.store.get(self.name)
        return _b64_md5(data) if data is not None else None

    def upload_from_filename(self, filename: str) -> None:
        if self.name in self._bucket.fail_uploads_for:
            self._bucket.attempts[self.name] = self._bucket.attempts.get(self.name, 0) + 1
            raise RuntimeError(f"injected upload failure for {self.name}")
        if self._bucket.corrupt_uploads_for.get(self.name, 0) > 0:
            self._bucket.corrupt_uploads_for[self.name] -= 1
            self._bucket.store[self.name] = b"corrupted-bytes"
            return
        with open(filename, "rb") as handle:
            self._bucket.store[self.name] = handle.read()

    def upload_from_string(self, data: str, content_type: str | None = None) -> None:
        self._bucket.store[self.name] = data.encode("utf-8")


class FakeBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self.store: dict[str, bytes] = {}
        # name -> remaining number of times an upload should fail outright
        self.fail_uploads_for: set[str] = set()
        # name -> remaining number of times an upload should write bad bytes
        self.corrupt_uploads_for: dict[str, int] = {}
        self.attempts: dict[str, int] = {}

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


class FakeClient:
    def __init__(self) -> None:
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name: str) -> FakeBucket:
        return self.buckets.setdefault(name, FakeBucket(name))


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    root = tmp_path / "src"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"alpha")
    (root / "b.pdf").write_bytes(b"bravo")
    (root / "note.txt").write_bytes(b"ignore me")
    sub = root / "sub"
    sub.mkdir()
    (sub / "c.pdf").write_bytes(b"charlie")
    return root


def make_config(source_dir: Path, **option_overrides: Any) -> UploadConfig:
    options = {
        "parallel_uploads": 2,
        "chunk_size_mb": 1,
        "verify_md5": True,
        "skip_if_exists": True,
        "retry_attempts": 3,
        "retry_backoff_seconds": [0, 0, 0],
        "manifest_path": "gs://maisys-data-dev/manifests/test_manifest.json",
        **option_overrides,
    }
    return UploadConfig(
        target=TargetConfig(
            bucket="maisys-data-dev", region="us-central1", storage_class="COLDLINE"
        ),
        options=OptionsConfig(**options),
        sources=[
            SourceConfig(
                name="pdfs",
                local_path=str(source_dir),
                remote_prefix="raw/drugs_com/general_pdfs",
                file_pattern="*.pdf",
                recursive=True,
            )
        ],
    )


# ──────────────────────────────────────────────────────────────────────────
# Config validation
# ──────────────────────────────────────────────────────────────────────────
def test_storage_class_normalized_and_validated() -> None:
    target = TargetConfig(bucket="b", region="r", storage_class="coldline")
    assert target.storage_class == "COLDLINE"
    with pytest.raises(ValidationError):
        TargetConfig(bucket="b", region="r", storage_class="GLACIER")


def test_manifest_path_must_be_gs_uri() -> None:
    with pytest.raises(ValidationError):
        OptionsConfig(manifest_path="/local/manifest.json")


def test_backoff_must_be_non_empty_and_non_negative() -> None:
    with pytest.raises(ValidationError):
        OptionsConfig(manifest_path="gs://b/m.json", retry_backoff_seconds=[])
    with pytest.raises(ValidationError):
        OptionsConfig(manifest_path="gs://b/m.json", retry_backoff_seconds=[-1])


def test_expected_max_below_min_rejected() -> None:
    with pytest.raises(ValidationError):
        SourceConfig(
            name="s",
            local_path="/x",
            remote_prefix="raw/x",
            expected_min_files=10,
            expected_max_files=5,
        )


def test_duplicate_source_names_rejected(source_dir: Path) -> None:
    with pytest.raises(ValidationError):
        UploadConfig(
            target=TargetConfig(bucket="b", region="r", storage_class="STANDARD"),
            options=OptionsConfig(manifest_path="gs://b/m.json"),
            sources=[
                SourceConfig(name="dup", local_path=str(source_dir), remote_prefix="a"),
                SourceConfig(name="dup", local_path=str(source_dir), remote_prefix="b"),
            ],
        )


def test_empty_sources_rejected() -> None:
    with pytest.raises(ValidationError):
        UploadConfig(
            target=TargetConfig(bucket="b", region="r", storage_class="STANDARD"),
            options=OptionsConfig(manifest_path="gs://b/m.json"),
            sources=[],
        )


def test_load_config_roundtrip(tmp_path: Path, source_dir: Path) -> None:
    config_yaml = f"""
target:
  bucket: maisys-data-dev
  region: us-central1
  storage_class: COLDLINE
options:
  parallel_uploads: 4
  chunk_size_mb: 8
  verify_md5: true
  skip_if_exists: true
  retry_attempts: 5
  retry_backoff_seconds: [1, 2, 4]
  manifest_path: gs://maisys-data-dev/manifests/phase_a1_manifest.json
sources:
  - name: drugs_com_general_pdfs
    local_path: {source_dir}
    remote_prefix: raw/drugs_com/general_pdfs
    file_pattern: "*.pdf"
    recursive: true
    expected_min_files: 1
    expected_max_files: 10
"""
    path = tmp_path / "cfg.yaml"
    path.write_text(config_yaml, encoding="utf-8")
    config = load_config(path)
    assert config.target.storage_class == "COLDLINE"
    assert config.options.chunk_size_bytes == 8 * 1024 * 1024
    assert config.sources[0].name == "drugs_com_general_pdfs"


# ──────────────────────────────────────────────────────────────────────────
# MD5 + enumeration helpers
# ──────────────────────────────────────────────────────────────────────────
def test_compute_md5_matches_hashlib(tmp_path: Path) -> None:
    data = b"the quick brown fox"
    f = tmp_path / "f.bin"
    f.write_bytes(data)
    hex_digest, b64_digest = compute_md5(f)
    assert hex_digest == hashlib.md5(data).hexdigest()
    assert b64_digest == _b64_md5(data)


def test_enumerate_respects_pattern_and_recursion(source_dir: Path) -> None:
    recursive = SourceConfig(
        name="s",
        local_path=str(source_dir),
        remote_prefix="r",
        file_pattern="*.pdf",
        recursive=True,
    )
    names = {p.name for p in enumerate_files(recursive)}
    assert names == {"a.pdf", "b.pdf", "c.pdf"}

    flat = SourceConfig(
        name="s",
        local_path=str(source_dir),
        remote_prefix="r",
        file_pattern="*.pdf",
        recursive=False,
    )
    assert {p.name for p in enumerate_files(flat)} == {"a.pdf", "b.pdf"}


def test_enumerate_missing_path_raises() -> None:
    source = SourceConfig(name="s", local_path="/no/such/dir", remote_prefix="r")
    with pytest.raises(FileNotFoundError):
        enumerate_files(source)


def test_check_file_count_bounds() -> None:
    source = SourceConfig(
        name="s", local_path="/x", remote_prefix="r", expected_min_files=2, expected_max_files=4
    )
    check_file_count(source, 3)  # within range -> no raise
    with pytest.raises(FileCountError):
        check_file_count(source, 1)
    with pytest.raises(FileCountError):
        check_file_count(source, 5)


def test_remote_object_name_preserves_subdirs(source_dir: Path) -> None:
    source = SourceConfig(
        name="s", local_path=str(source_dir), remote_prefix="raw/x/", recursive=True
    )
    name = remote_object_name(source, source_dir / "sub" / "c.pdf")
    assert name == "raw/x/sub/c.pdf"


def test_parse_gs_uri() -> None:
    assert parse_gs_uri("gs://bucket/path/to/obj.json") == ("bucket", "path/to/obj.json")
    with pytest.raises(ValueError):
        parse_gs_uri("s3://bucket/obj")
    with pytest.raises(ValueError):
        parse_gs_uri("gs://bucket-only")


# ──────────────────────────────────────────────────────────────────────────
# Upload behaviour
# ──────────────────────────────────────────────────────────────────────────
def test_full_run_uploads_all_and_writes_manifest(source_dir: Path) -> None:
    client = FakeClient()
    config = make_config(source_dir)
    uploader = GcsUploader(client, config, sleep=lambda _: None)

    manifest = uploader.run("cfg.yaml")
    assert manifest.totals["files_uploaded"] == 3
    assert manifest.totals["files_failed"] == 0

    bucket = client.bucket("maisys-data-dev")
    assert bucket.store["raw/drugs_com/general_pdfs/a.pdf"] == b"alpha"
    assert bucket.store["raw/drugs_com/general_pdfs/sub/c.pdf"] == b"charlie"

    uri = uploader.write_manifest(manifest)
    assert uri == config.options.manifest_path
    written = json.loads(bucket.store["manifests/test_manifest.json"].decode("utf-8"))
    assert written["run_id"] == manifest.run_id
    assert written["totals"]["files_uploaded"] == 3
    assert len(written["sources"][0]["files"]) == 3


def test_skip_if_exists_when_md5_matches(source_dir: Path) -> None:
    client = FakeClient()
    config = make_config(source_dir)
    bucket = client.bucket("maisys-data-dev")
    # Pre-seed one object with matching content -> should be skipped.
    bucket.store["raw/drugs_com/general_pdfs/a.pdf"] = b"alpha"

    uploader = GcsUploader(client, config, sleep=lambda _: None)
    stats = uploader.process_source(config.sources[0])
    assert stats.files_skipped == 1
    assert stats.files_uploaded == 2


def test_force_reuploads_existing(source_dir: Path) -> None:
    client = FakeClient()
    config = make_config(source_dir)
    bucket = client.bucket("maisys-data-dev")
    bucket.store["raw/drugs_com/general_pdfs/a.pdf"] = b"alpha"

    uploader = GcsUploader(client, config, force=True, sleep=lambda _: None)
    stats = uploader.process_source(config.sources[0])
    assert stats.files_skipped == 0
    assert stats.files_uploaded == 3


def test_stale_md5_is_not_skipped(source_dir: Path) -> None:
    client = FakeClient()
    config = make_config(source_dir)
    bucket = client.bucket("maisys-data-dev")
    # Existing object has different content -> must be re-uploaded.
    bucket.store["raw/drugs_com/general_pdfs/a.pdf"] = b"OUTDATED"

    uploader = GcsUploader(client, config, sleep=lambda _: None)
    stats = uploader.process_source(config.sources[0])
    assert stats.files_uploaded == 3
    assert bucket.store["raw/drugs_com/general_pdfs/a.pdf"] == b"alpha"


def test_retry_then_succeed(source_dir: Path) -> None:
    client = FakeClient()
    config = make_config(source_dir, retry_attempts=3)
    bucket = client.bucket("maisys-data-dev")

    target = "raw/drugs_com/general_pdfs/a.pdf"
    # Corrupt the first upload so MD5 verification fails once, then succeed.
    bucket.corrupt_uploads_for[target] = 1

    uploader = GcsUploader(client, config, sleep=lambda _: None)
    entry = uploader.upload_file(config.sources[0], source_dir / "a.pdf")
    assert entry.status == "uploaded"
    assert entry.attempts == 2
    assert bucket.store[target] == b"alpha"


def test_retry_exhausted_marks_failed(source_dir: Path) -> None:
    client = FakeClient()
    config = make_config(source_dir, retry_attempts=3)
    bucket = client.bucket("maisys-data-dev")
    target = "raw/drugs_com/general_pdfs/a.pdf"
    bucket.fail_uploads_for.add(target)

    uploader = GcsUploader(client, config, sleep=lambda _: None)
    entry = uploader.upload_file(config.sources[0], source_dir / "a.pdf")
    assert entry.status == "failed"
    assert entry.attempts == 3
    assert entry.error is not None


def test_run_aborts_when_count_out_of_range(source_dir: Path) -> None:
    client = FakeClient()
    config = make_config(source_dir)
    config.sources[0].expected_min_files = 100  # only 3 present
    uploader = GcsUploader(client, config, sleep=lambda _: None)
    with pytest.raises(FileCountError):
        uploader.run("cfg.yaml")


def test_dry_run_does_not_upload(source_dir: Path) -> None:
    client = FakeClient()
    config = make_config(source_dir)
    uploader = GcsUploader(client, config, dry_run=True, sleep=lambda _: None)
    manifest = uploader.run("cfg.yaml")
    assert manifest.totals["files_uploaded"] == 3
    # Nothing actually written to the bucket.
    assert client.bucket("maisys-data-dev").store == {}


def test_verify_disabled_skips_on_existence(source_dir: Path) -> None:
    client = FakeClient()
    config = make_config(source_dir, verify_md5=False)
    bucket = client.bucket("maisys-data-dev")
    # Different content, but verify_md5 is off, so existence alone skips it.
    bucket.store["raw/drugs_com/general_pdfs/a.pdf"] = b"WHATEVER"
    uploader = GcsUploader(client, config, sleep=lambda _: None)
    stats = uploader.process_source(config.sources[0])
    assert stats.files_skipped == 1
    assert stats.files_uploaded == 2


# ──────────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ──────────────────────────────────────────────────────────────────────────
def _write_config_file(tmp_path: Path, source_dir: Path) -> Path:
    config_yaml = f"""
target:
  bucket: maisys-data-dev
  region: us-central1
  storage_class: COLDLINE
options:
  parallel_uploads: 2
  chunk_size_mb: 1
  verify_md5: true
  skip_if_exists: true
  retry_attempts: 2
  retry_backoff_seconds: [0]
  manifest_path: gs://maisys-data-dev/manifests/test_manifest.json
sources:
  - name: pdfs
    local_path: {source_dir}
    remote_prefix: raw/drugs_com/general_pdfs
    file_pattern: "*.pdf"
    recursive: true
"""
    path = tmp_path / "cfg.yaml"
    path.write_text(config_yaml, encoding="utf-8")
    return path


def test_main_dry_run_exit_zero(
    tmp_path: Path, source_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient()
    monkeypatch.setattr("cloud.upload_local_to_gcs.storage.Client", lambda *a, **k: fake)
    cfg = _write_config_file(tmp_path, source_dir)
    rc = main(["--config", str(cfg), "--dry-run", "--parallel", "2"])
    assert rc == 0
    assert fake.bucket("maisys-data-dev").store == {}


def test_main_real_run_writes_manifest(
    tmp_path: Path, source_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeClient()
    monkeypatch.setattr("cloud.upload_local_to_gcs.storage.Client", lambda *a, **k: fake)
    cfg = _write_config_file(tmp_path, source_dir)
    rc = main(["--config", str(cfg)])
    assert rc == 0
    store = fake.bucket("maisys-data-dev").store
    assert "manifests/test_manifest.json" in store


def test_main_bad_config_returns_two(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("target: {bucket: b}\n", encoding="utf-8")
    rc = main(["--config", str(bad)])
    assert rc == 2


def test_main_missing_config_returns_two(tmp_path: Path) -> None:
    rc = main(["--config", str(tmp_path / "nope.yaml")])
    assert rc == 2


def test_md5_mismatch_error_is_exception() -> None:
    assert issubclass(Md5MismatchError, Exception)
