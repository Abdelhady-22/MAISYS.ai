"""One-time bulk upload of local datasets to Google Cloud Storage.

This is the single deliberate exception to the cloud-only rule: it is the
laptop-to-GCS bridge used in Phase A1 (Laptop 1, drugs.com PDFs) and Phase A2
(Laptop 2, structured datasets). Every other script in ``data-pipeline``
reads and writes cloud URIs only.

Behaviour
---------
For each source listed in the YAML config the uploader:

1. Enumerates local files honouring ``file_pattern`` and ``recursive``.
2. Verifies the file count against ``expected_min_files`` / ``expected_max_files``
   and aborts with a clear error if the count is outside the range.
3. Computes the local MD5 of every file.
4. Skips files already present in GCS with a matching MD5 (when
   ``skip_if_exists`` is set and ``--force`` is not given) — this is what makes
   a killed run resumable.
5. Uploads the remaining files with the configured storage class and chunk
   size, retrying on failure with the configured backoff.
6. Re-verifies the post-upload MD5 and retries on mismatch.

Progress is streamed with per-source and overall ``tqdm`` bars. A JSON manifest
recording every file (local path, remote URI, MD5, size, status, attempts) is
written to ``options.manifest_path`` (a ``gs://`` URI). The process exits 0 only
if every file succeeded.

Usage
-----
    python data-pipeline/cloud/upload_local_to_gcs.py \\
        --config data-pipeline/cloud/laptop1_sources.yaml \\
        --parallel 8 [--dry-run] [--force] [--verbose]

Authentication uses Application Default Credentials
(``gcloud auth application-default login``); no service-account JSON is read
by this script.
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import hashlib
import json
import sys
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog
import yaml
from google.cloud import storage
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from tqdm import tqdm

log = structlog.get_logger()

VALID_STORAGE_CLASSES = {"STANDARD", "NEARLINE", "COLDLINE", "ARCHIVE"}
FileStatus = Literal["uploaded", "skipped", "failed"]


# ──────────────────────────────────────────────────────────────────────────
# Configuration models (Pydantic v2)
# ──────────────────────────────────────────────────────────────────────────
class TargetConfig(BaseModel):
    """Cloud destination shared by every source in a config."""

    bucket: str = Field(min_length=1)
    region: str = Field(min_length=1)
    storage_class: str

    @field_validator("storage_class")
    @classmethod
    def _validate_storage_class(cls, value: str) -> str:
        upper = value.upper()
        if upper not in VALID_STORAGE_CLASSES:
            allowed = ", ".join(sorted(VALID_STORAGE_CLASSES))
            raise ValueError(f"storage_class must be one of {allowed}; got {value!r}")
        return upper


class OptionsConfig(BaseModel):
    """Upload behaviour knobs."""

    parallel_uploads: int = Field(default=8, ge=1)
    chunk_size_mb: int = Field(default=16, ge=1)
    verify_md5: bool = True
    skip_if_exists: bool = True
    retry_attempts: int = Field(default=5, ge=1)
    retry_backoff_seconds: list[float] = Field(default_factory=lambda: [1.0, 2.0, 4.0, 8.0, 16.0])
    manifest_path: str

    @field_validator("retry_backoff_seconds")
    @classmethod
    def _validate_backoff(cls, value: list[float]) -> list[float]:
        if not value:
            raise ValueError("retry_backoff_seconds must contain at least one value")
        if any(v < 0 for v in value):
            raise ValueError("retry_backoff_seconds values must be non-negative")
        return value

    @field_validator("manifest_path")
    @classmethod
    def _validate_manifest_path(cls, value: str) -> str:
        if not value.startswith("gs://"):
            raise ValueError(f"manifest_path must be a gs:// URI; got {value!r}")
        return value

    @property
    def chunk_size_bytes(self) -> int:
        return self.chunk_size_mb * 1024 * 1024


class SourceConfig(BaseModel):
    """A single local folder mapped to a GCS prefix."""

    name: str = Field(min_length=1)
    local_path: str = Field(min_length=1)
    remote_prefix: str = Field(min_length=1)
    file_pattern: str = "*"
    recursive: bool = True
    expected_min_files: int | None = Field(default=None, ge=0)
    expected_max_files: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_counts(self) -> SourceConfig:
        lo, hi = self.expected_min_files, self.expected_max_files
        if lo is not None and hi is not None and hi < lo:
            raise ValueError(
                f"source {self.name!r}: expected_max_files ({hi}) "
                f"is less than expected_min_files ({lo})"
            )
        return self


class UploadConfig(BaseModel):
    """Top-level config: destination, options, and the list of sources."""

    target: TargetConfig
    options: OptionsConfig
    sources: list[SourceConfig] = Field(min_length=1)

    @field_validator("sources")
    @classmethod
    def _validate_unique_names(cls, value: list[SourceConfig]) -> list[SourceConfig]:
        names = [s.name for s in value]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"duplicate source names: {', '.join(dupes)}")
        return value


# ──────────────────────────────────────────────────────────────────────────
# Manifest models
# ──────────────────────────────────────────────────────────────────────────
class FileEntry(BaseModel):
    """Per-file record in the manifest."""

    local_path: str
    remote_uri: str
    md5: str
    size_bytes: int
    status: FileStatus
    attempts: int
    error: str | None = None


class SourceStats(BaseModel):
    """Per-source rollup in the manifest."""

    name: str
    remote_prefix: str
    files_uploaded: int = 0
    files_skipped: int = 0
    files_failed: int = 0
    total_bytes: int = 0
    files: list[FileEntry] = Field(default_factory=list)


class Manifest(BaseModel):
    """The JSON manifest written to GCS at the end of a run."""

    run_id: str
    started_at: str
    completed_at: str | None = None
    config_path: str
    target_bucket: str
    sources: list[SourceStats] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
class Md5MismatchError(Exception):
    """Raised when a post-upload MD5 does not match the local file's MD5."""


class FileCountError(Exception):
    """Raised when a source's file count is outside its expected range."""


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def compute_md5(path: Path, chunk: int = 1024 * 1024) -> tuple[str, str]:
    """Return ``(hex_digest, base64_digest)`` of a file's MD5.

    GCS stores the MD5 as a base64 string in ``blob.md5_hash``; the hex form is
    kept in the manifest for human readability.
    """
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    raw = digest.digest()
    return digest.hexdigest(), base64.b64encode(raw).decode("ascii")


def enumerate_files(source: SourceConfig) -> list[Path]:
    """Enumerate the local files for a source, honouring pattern and recursion.

    Results are sorted for deterministic ordering across runs.
    """
    root = Path(source.local_path)
    if not root.exists():
        raise FileNotFoundError(f"source {source.name!r}: local_path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"source {source.name!r}: local_path is not a directory: {root}")

    candidates = root.rglob("*") if source.recursive else root.glob("*")
    matched = [
        p for p in candidates if p.is_file() and fnmatch.fnmatch(p.name, source.file_pattern)
    ]
    return sorted(matched)


def check_file_count(source: SourceConfig, count: int) -> None:
    """Abort if a source's file count falls outside its expected range."""
    lo, hi = source.expected_min_files, source.expected_max_files
    if lo is not None and count < lo:
        raise FileCountError(f"source {source.name!r}: found {count} files, expected at least {lo}")
    if hi is not None and count > hi:
        raise FileCountError(f"source {source.name!r}: found {count} files, expected at most {hi}")


def remote_object_name(source: SourceConfig, local_file: Path) -> str:
    """Build the GCS object name for a local file under a source.

    Subdirectory structure beneath ``local_path`` is preserved under
    ``remote_prefix``.
    """
    rel = local_file.relative_to(Path(source.local_path))
    prefix = source.remote_prefix.strip("/")
    rel_posix = rel.as_posix()
    return f"{prefix}/{rel_posix}" if prefix else rel_posix


def parse_gs_uri(uri: str) -> tuple[str, str]:
    """Split a ``gs://bucket/object`` URI into ``(bucket, object_name)``."""
    if not uri.startswith("gs://"):
        raise ValueError(f"not a gs:// URI: {uri!r}")
    without_scheme = uri[len("gs://") :]
    bucket, _, object_name = without_scheme.partition("/")
    if not bucket or not object_name:
        raise ValueError(f"gs:// URI must include a bucket and object path: {uri!r}")
    return bucket, object_name


# ──────────────────────────────────────────────────────────────────────────
# Uploader
# ──────────────────────────────────────────────────────────────────────────
class GcsUploader:
    """Uploads sources to GCS, producing a manifest.

    The GCS ``client`` is injected so the upload logic can be exercised against
    a mock in tests without touching a live service.
    """

    def __init__(
        self,
        client: Any,
        config: UploadConfig,
        *,
        force: bool = False,
        dry_run: bool = False,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.config = config
        self.force = force
        self.dry_run = dry_run
        self.sleep = sleep
        self.bucket = client.bucket(config.target.bucket)

    def remote_md5(self, object_name: str) -> str | None:
        """Return the base64 MD5 of an existing GCS object, or ``None``."""
        blob = self.bucket.blob(object_name)
        if not blob.exists():
            return None
        blob.reload()
        value: str | None = blob.md5_hash
        return value

    def _backoff_for_attempt(self, attempt: int) -> float:
        backoff = self.config.options.retry_backoff_seconds
        return backoff[min(attempt, len(backoff) - 1)]

    def upload_file(self, source: SourceConfig, local_file: Path) -> FileEntry:
        """Upload (or skip) a single file, returning its manifest entry."""
        options = self.config.options
        object_name = remote_object_name(source, local_file)
        remote_uri = f"gs://{self.config.target.bucket}/{object_name}"
        local_hex, local_b64 = compute_md5(local_file)
        size_bytes = local_file.stat().st_size

        def entry(status: FileStatus, attempts: int, error: str | None = None) -> FileEntry:
            return FileEntry(
                local_path=str(local_file),
                remote_uri=remote_uri,
                md5=local_hex,
                size_bytes=size_bytes,
                status=status,
                attempts=attempts,
                error=error,
            )

        # Resume: skip files already present with a matching MD5.
        if options.skip_if_exists and not self.force:
            existing = self.remote_md5(object_name)
            if existing is not None and (not options.verify_md5 or existing == local_b64):
                log.debug("skip_existing", source=source.name, remote=remote_uri)
                return entry("skipped", attempts=0)

        if self.dry_run:
            log.info("plan_upload", source=source.name, remote=remote_uri, size_bytes=size_bytes)
            return entry("uploaded", attempts=0)

        last_error: str | None = None
        for attempt in range(options.retry_attempts):
            try:
                blob = self.bucket.blob(object_name)
                blob.storage_class = self.config.target.storage_class
                blob.chunk_size = options.chunk_size_bytes
                blob.upload_from_filename(str(local_file))
                if options.verify_md5:
                    uploaded = self.remote_md5(object_name)
                    if uploaded != local_b64:
                        raise Md5MismatchError(
                            f"{remote_uri}: post-upload MD5 {uploaded!r} != local {local_b64!r}"
                        )
                log.debug("uploaded", source=source.name, remote=remote_uri, attempt=attempt + 1)
                return entry("uploaded", attempts=attempt + 1)
            except Exception as exc:  # noqa: BLE001 - recorded and retried
                last_error = str(exc)
                log.warning(
                    "upload_failed",
                    source=source.name,
                    remote=remote_uri,
                    attempt=attempt + 1,
                    error=last_error,
                )
                if attempt < options.retry_attempts - 1:
                    self.sleep(self._backoff_for_attempt(attempt))

        return entry("failed", attempts=options.retry_attempts, error=last_error)

    def process_source(self, source: SourceConfig, overall: tqdm[Any] | None = None) -> SourceStats:
        """Enumerate, validate, and upload one source."""
        files = enumerate_files(source)
        check_file_count(source, len(files))
        log.info("source_start", source=source.name, files=len(files))

        stats = SourceStats(name=source.name, remote_prefix=source.remote_prefix)
        parallel = self.config.options.parallel_uploads

        with (
            tqdm(total=len(files), desc=source.name, unit="file", leave=False) as source_bar,
            ThreadPoolExecutor(max_workers=parallel) as pool,
        ):
            futures: dict[Future[FileEntry], Path] = {
                pool.submit(self.upload_file, source, f): f for f in files
            }
            for future in as_completed(futures):
                result = future.result()
                stats.files.append(result)
                if result.status == "uploaded":
                    stats.files_uploaded += 1
                    stats.total_bytes += result.size_bytes
                elif result.status == "skipped":
                    stats.files_skipped += 1
                    stats.total_bytes += result.size_bytes
                else:
                    stats.files_failed += 1
                source_bar.update(1)
                if overall is not None:
                    overall.update(1)

        stats.files.sort(key=lambda e: e.local_path)
        log.info(
            "source_done",
            source=source.name,
            uploaded=stats.files_uploaded,
            skipped=stats.files_skipped,
            failed=stats.files_failed,
        )
        return stats

    def run(self, config_path: str) -> Manifest:
        """Process every source and assemble (but do not yet write) the manifest."""
        manifest = Manifest(
            run_id=str(uuid.uuid4()),
            started_at=_utc_now_iso(),
            config_path=config_path,
            target_bucket=self.config.target.bucket,
        )

        # Enumerate + count-check every source up front so a bad count aborts
        # the whole run before any bytes are uploaded.
        enumerated: list[tuple[SourceConfig, list[Path]]] = []
        for source in self.config.sources:
            files = enumerate_files(source)
            check_file_count(source, len(files))
            enumerated.append((source, files))
        total_files = sum(len(files) for _, files in enumerated)

        with tqdm(total=total_files, desc="overall", unit="file") as overall:
            for source, _files in enumerated:
                manifest.sources.append(self.process_source(source, overall))

        manifest.completed_at = _utc_now_iso()
        manifest.totals = {
            "files_uploaded": sum(s.files_uploaded for s in manifest.sources),
            "files_skipped": sum(s.files_skipped for s in manifest.sources),
            "files_failed": sum(s.files_failed for s in manifest.sources),
            "total_bytes": sum(s.total_bytes for s in manifest.sources),
        }
        return manifest

    def write_manifest(self, manifest: Manifest) -> str:
        """Upload the manifest JSON to ``options.manifest_path`` and return the URI."""
        uri = self.config.options.manifest_path
        bucket_name, object_name = parse_gs_uri(uri)
        payload = json.dumps(manifest.model_dump(), indent=2, sort_keys=False)
        blob = self.client.bucket(bucket_name).blob(object_name)
        blob.upload_from_string(payload, content_type="application/json")
        log.info("manifest_written", uri=uri)
        return uri


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def load_config(path: Path) -> UploadConfig:
    """Load and validate a YAML config into an :class:`UploadConfig`."""
    if not path.exists():
        raise FileNotFoundError(f"config not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError(f"config must be a YAML mapping; got {type(raw).__name__}")
    return UploadConfig.model_validate(raw)


def configure_logging(verbose: bool) -> None:
    """Configure structlog for human-readable console output."""
    import logging

    level = logging.DEBUG if verbose else logging.INFO
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="upload_local_to_gcs",
        description="One-time bulk upload of local datasets to Google Cloud Storage.",
    )
    parser.add_argument(
        "--config", required=True, type=Path, help="Path to the YAML sources config."
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=None,
        help="Override options.parallel_uploads from the config.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned uploads without uploading or writing a manifest.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-upload every file even if a matching object already exists.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug-level logging.")
    return parser


def print_summary(manifest: Manifest, dry_run: bool) -> None:
    """Print a one-line-per-source summary plus totals."""
    label = "DRY RUN" if dry_run else "RUN"
    print(f"\n=== {label} summary (run_id={manifest.run_id}) ===")
    for source in manifest.sources:
        verb = "would upload" if dry_run else "uploaded"
        print(
            f"  {source.name}: {verb}={source.files_uploaded} "
            f"skipped={source.files_skipped} failed={source.files_failed} "
            f"bytes={source.total_bytes}"
        )
    totals = manifest.totals
    print(
        f"  TOTAL: uploaded={totals.get('files_uploaded', 0)} "
        f"skipped={totals.get('files_skipped', 0)} "
        f"failed={totals.get('files_failed', 0)} "
        f"bytes={totals.get('total_bytes', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        log.error("config_error", error=str(exc))
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if args.parallel is not None:
        if args.parallel < 1:
            print("Config error: --parallel must be >= 1", file=sys.stderr)
            return 2
        config.options.parallel_uploads = args.parallel

    client = storage.Client()
    uploader = GcsUploader(client, config, force=args.force, dry_run=args.dry_run)

    try:
        manifest = uploader.run(str(args.config))
    except (FileCountError, FileNotFoundError, NotADirectoryError) as exc:
        log.error("run_aborted", error=str(exc))
        print(f"Aborted: {exc}", file=sys.stderr)
        return 2

    if not args.dry_run:
        uploader.write_manifest(manifest)

    print_summary(manifest, args.dry_run)

    failed = manifest.totals.get("files_failed", 0)
    if failed:
        print(f"\n{failed} file(s) failed to upload.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
