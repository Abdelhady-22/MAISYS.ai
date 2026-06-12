"""Download the ChatDoctor instruction datasets from GitHub to GCS (Phase B).

ChatDoctor (``DATA_PLAN.md`` §2.2, items 18–19) ships two instruction-tuning
files in its GitHub repo:

* ``HealthCareMagic-100k.json``
* ``iCliniq-10k.json``

This script shallow-clones the repo into a temp directory, locates and validates
those two files, uploads them as-is to
``gs://<bucket>/beta_training/raw_downloads/chatdoctor_github/``, and writes a
manifest recording each file's MD5, record count, and the repo commit SHA at
download time. The temp clone is always removed (even on failure).

It is idempotent: if the manifest already records the current commit SHA, the
upload is skipped unless ``--force`` is given.

Usage
-----
    python data-pipeline/downloaders/download_chatdoctor.py \\
        --output-bucket gs://maisys-data-dev/beta_training/raw_downloads/chatdoctor_github \\
        [--repo-url https://github.com/Kent0n-Li/ChatDoctor.git] \\
        [--dry-run] [--force] [--verbose]

Where it runs: a GCP VM in Phase B. Output is cloud-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog
from google.cloud import storage
from pydantic import BaseModel, Field

log = structlog.get_logger()

DEFAULT_REPO_URL = "https://github.com/Kent0n-Li/ChatDoctor.git"
EXPECTED_FILES = ("HealthCareMagic-100k.json", "iCliniq-10k.json")
REQUIRED_KEYS = {"instruction", "input", "output"}

# Injected for tests: runs a git subcommand and returns its stdout.
GitRunner = Callable[[list[str], "str | None"], str]


# ──────────────────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────────────────
class CloneError(Exception):
    """Raised when the git clone or SHA lookup fails."""


class DatasetValidationError(Exception):
    """Raised when an expected file is missing or malformed."""


# ──────────────────────────────────────────────────────────────────────────
# Manifest models
# ──────────────────────────────────────────────────────────────────────────
class FileEntry(BaseModel):
    filename: str
    remote_uri: str
    md5: str
    size_bytes: int
    record_count: int


class ChatDoctorManifest(BaseModel):
    run_id: str
    downloaded_at: str
    repo_url: str
    commit_sha: str
    status: Literal["downloaded", "skipped"]
    files: list[FileEntry] = Field(default_factory=list)
    total_records: int = 0
    total_bytes: int = 0


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _run_git(args: list[str], cwd: str | None = None) -> str:
    """Run a git subcommand and return stdout (raises CloneError on failure)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        raise CloneError(f"git {' '.join(args)} failed: {stderr or exc}") from exc
    return result.stdout


def parse_gs_uri(uri: str) -> tuple[str, str]:
    """Split ``gs://bucket/prefix`` into ``(bucket, prefix)`` (prefix may be empty)."""
    if not uri.startswith("gs://"):
        raise ValueError(f"not a gs:// URI: {uri!r}")
    without_scheme = uri[len("gs://") :]
    bucket, _, prefix = without_scheme.partition("/")
    if not bucket:
        raise ValueError(f"gs:// URI must include a bucket: {uri!r}")
    return bucket, prefix.strip("/")


def compute_md5(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def find_file(root: Path, filename: str) -> Path:
    """Locate ``filename`` anywhere under ``root`` (the repo may nest it)."""
    matches = sorted(root.rglob(filename))
    if not matches:
        raise DatasetValidationError(f"expected file not found in repo: {filename}")
    return matches[0]


def validate_records(path: Path) -> int:
    """Validate the file is a list of instruction objects; return the record count.

    Each record must be an object containing ``instruction``, ``input`` and
    ``output`` keys.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise DatasetValidationError(f"{path.name}: invalid JSON ({exc})") from exc

    if not isinstance(data, list):
        raise DatasetValidationError(
            f"{path.name}: expected a JSON list, got {type(data).__name__}"
        )
    if not data:
        raise DatasetValidationError(f"{path.name}: file contains no records")

    for index, record in enumerate(data):
        if not isinstance(record, dict):
            raise DatasetValidationError(
                f"{path.name}: record {index} is {type(record).__name__}, expected object"
            )
        missing = REQUIRED_KEYS - record.keys()
        if missing:
            raise DatasetValidationError(
                f"{path.name}: record {index} missing keys: {', '.join(sorted(missing))}"
            )
    return len(data)


# ──────────────────────────────────────────────────────────────────────────
# Downloader
# ──────────────────────────────────────────────────────────────────────────
class ChatDoctorDownloader:
    """Clones ChatDoctor, validates the two datasets, and uploads them to GCS.

    The storage client and the git runner are injected so the flow can be tested
    against fakes without a network, a real clone, or a live bucket.
    """

    def __init__(
        self,
        client: Any,
        output_uri: str,
        *,
        repo_url: str = DEFAULT_REPO_URL,
        force: bool = False,
        dry_run: bool = False,
        git_runner: GitRunner | None = None,
    ) -> None:
        self.client = client
        self.output_uri = output_uri
        self.bucket_name, self.prefix = parse_gs_uri(output_uri)
        self.bucket = client.bucket(self.bucket_name)
        self.repo_url = repo_url
        self.force = force
        self.dry_run = dry_run
        # Resolve the default at runtime (not as a bound default arg) so tests
        # can monkeypatch the module-level runner and main() picks it up.
        self.git_runner = git_runner if git_runner is not None else _run_git

    def _object_name(self, filename: str) -> str:
        return f"{self.prefix}/{filename}" if self.prefix else filename

    def _manifest_object_name(self) -> str:
        return self._object_name("_manifest.json")

    def existing_manifest(self) -> ChatDoctorManifest | None:
        blob = self.bucket.blob(self._manifest_object_name())
        if not blob.exists():
            return None
        try:
            payload: str = blob.download_as_text()
            return ChatDoctorManifest.model_validate_json(payload)
        except Exception as exc:  # noqa: BLE001 - corrupt manifest -> re-download
            log.warning("manifest_unreadable", error=str(exc))
            return None

    def _clone(self, dest: str) -> str:
        """Shallow-clone the repo into ``dest`` and return its commit SHA."""
        self.git_runner(["clone", "--depth", "1", self.repo_url, dest], None)
        sha = self.git_runner(["-C", dest, "rev-parse", "HEAD"], None).strip()
        if not sha:
            raise CloneError("could not resolve commit SHA after clone")
        return sha

    def write_manifest(self, manifest: ChatDoctorManifest) -> str:
        object_name = self._manifest_object_name()
        uri = f"gs://{self.bucket_name}/{object_name}"
        blob = self.bucket.blob(object_name)
        blob.upload_from_string(
            json.dumps(manifest.model_dump(), indent=2), content_type="application/json"
        )
        log.info("manifest_written", uri=uri)
        return uri

    def run(self) -> ChatDoctorManifest:
        """Execute the full clone → validate → upload → manifest flow.

        The temp clone directory is always removed via ``TemporaryDirectory``,
        even when an exception propagates.
        """
        with tempfile.TemporaryDirectory(prefix="chatdoctor_") as tmp:
            commit_sha = self._clone(tmp)
            log.info("cloned", repo=self.repo_url, sha=commit_sha)

            existing = None if self.force else self.existing_manifest()
            if existing is not None and existing.commit_sha == commit_sha:
                log.info("skip_existing", sha=commit_sha)
                return existing.model_copy(update={"status": "skipped"})

            # Locate + validate both files before uploading anything.
            located: list[tuple[str, Path, int]] = []
            for filename in EXPECTED_FILES:
                path = find_file(Path(tmp), filename)
                count = validate_records(path)
                located.append((filename, path, count))

            if self.dry_run:
                log.info("plan_upload", sha=commit_sha, files=[f for f, _, _ in located])
                return ChatDoctorManifest(
                    run_id=str(uuid.uuid4()),
                    downloaded_at=_utc_now_iso(),
                    repo_url=self.repo_url,
                    commit_sha=commit_sha,
                    status="downloaded",
                    total_records=sum(c for _, _, c in located),
                )

            entries: list[FileEntry] = []
            for filename, path, count in located:
                object_name = self._object_name(filename)
                self.bucket.blob(object_name).upload_from_filename(str(path))
                entries.append(
                    FileEntry(
                        filename=filename,
                        remote_uri=f"gs://{self.bucket_name}/{object_name}",
                        md5=compute_md5(path),
                        size_bytes=path.stat().st_size,
                        record_count=count,
                    )
                )

            manifest = ChatDoctorManifest(
                run_id=str(uuid.uuid4()),
                downloaded_at=_utc_now_iso(),
                repo_url=self.repo_url,
                commit_sha=commit_sha,
                status="downloaded",
                files=entries,
                total_records=sum(e.record_count for e in entries),
                total_bytes=sum(e.size_bytes for e in entries),
            )
            self.write_manifest(manifest)
            log.info(
                "downloaded",
                sha=commit_sha,
                records=manifest.total_records,
                bytes=manifest.total_bytes,
            )
            return manifest


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def configure_logging(verbose: bool) -> None:
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
        prog="download_chatdoctor",
        description="Download ChatDoctor instruction datasets from GitHub to GCS.",
    )
    parser.add_argument("--output-bucket", required=True, help="GCS gs:// URI prefix for output.")
    parser.add_argument(
        "--repo-url", default=DEFAULT_REPO_URL, help="ChatDoctor git repository URL."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Clone and validate, but do not upload or write a manifest.",
    )
    parser.add_argument(
        "--force", action="store_true", help="Re-upload even if the SHA is unchanged."
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging.")
    return parser


def print_summary(manifest: ChatDoctorManifest, dry_run: bool) -> None:
    label = "DRY RUN" if dry_run else "RUN"
    print(f"\n=== ChatDoctor download {label} (run_id={manifest.run_id}) ===")
    print(f"  repo={manifest.repo_url}")
    print(f"  commit={manifest.commit_sha} status={manifest.status}")
    if manifest.files:
        for entry in manifest.files:
            print(
                f"  {entry.filename}: records={entry.record_count} "
                f"bytes={entry.size_bytes} md5={entry.md5}"
            )
    print(f"  TOTAL: records={manifest.total_records} bytes={manifest.total_bytes}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    try:
        parse_gs_uri(args.output_bucket)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    client = storage.Client()
    downloader = ChatDoctorDownloader(
        client,
        args.output_bucket,
        repo_url=args.repo_url,
        force=args.force,
        dry_run=args.dry_run,
    )

    try:
        manifest = downloader.run()
    except (CloneError, DatasetValidationError) as exc:
        log.error("download_failed", error=str(exc))
        print(f"Failed: {exc}", file=sys.stderr)
        return 1

    print_summary(manifest, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
