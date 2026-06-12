"""Download the MTSamples medical-transcriptions Kaggle dataset to GCS (Phase B).

This pulls the Kaggle dataset (default ``tboyle10/medicaltranscriptions``) with
the official ``kaggle`` Python library, uploads the extracted CSV(s) to
``gs://<bucket>/.../mtsamples_kaggle/``, and writes a manifest
(``_manifest.json``) recording each file's MD5, row count, and columns.

Behaviour
---------
1. Resolve the Kaggle credentials (``kaggle.json``) from the ``kaggle-api-key``
   secret in GCP Secret Manager. Missing/unreadable credentials fail with clear
   instructions for creating the secret.
2. Write the credentials to a private temporary directory and point the Kaggle
   library at it via ``KAGGLE_CONFIG_DIR`` (chosen over ``~/.kaggle`` so nothing
   is written to the invoking user's home, the temp dir is isolated per run, and
   cleanup is unconditional). The file is created ``0o600``.
3. Download + unzip the dataset into a temp dir with the Kaggle library (not the
   CLI).
4. Upload every extracted CSV to the output prefix.
5. Write the manifest with per-file MD5, row count, and columns.
6. Clean up all temp files.
7. Idempotent via a manifest check: if ``_manifest.json`` already records a
   successful download, the dataset is skipped unless ``--force`` is given.

Usage
-----
    python data-pipeline/downloaders/download_mtsamples_kaggle.py \\
        --output-bucket gs://maisys-data-dev/beta_training/raw_downloads/mtsamples_kaggle \\
        --dataset tboyle10/medicaltranscriptions \\
        [--dry-run] [--force] [--verbose]

Where it runs: a GCP VM in Phase B. Output is cloud-only; nothing persists on a
laptop.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog
from google.cloud import storage
from pydantic import BaseModel, Field

log = structlog.get_logger()

DownloadStatus = Literal["downloaded", "skipped", "failed"]

# Injectable function types — the defaults lazily import optional libraries
# (kaggle, google-cloud-secret-manager) so the module imports cleanly and tests
# can substitute fakes without those libraries installed.
CredentialsProvider = Callable[[], str]
DownloadFn = Callable[[str, str], None]


# ──────────────────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────────────────
class KaggleCredentialsError(Exception):
    """Raised when Kaggle credentials cannot be resolved or are malformed."""


class NoCsvError(Exception):
    """Raised when the downloaded dataset contains no CSV files."""


# ──────────────────────────────────────────────────────────────────────────
# Credential resolution (temporary shim)
# ──────────────────────────────────────────────────────────────────────────
def resolve_kaggle_credentials(secret_name: str = "kaggle-api-key") -> str:
    """Return the ``kaggle.json`` payload from GCP Secret Manager.

    NOTE: This is a temporary shim. Once ``shared/security`` exists it should be
    replaced by ``shared.security.get_secret("kaggle-api-key")`` — the canonical
    credential path per ``data-pipeline/CLAUDE.md``.

    Raises:
        KaggleCredentialsError: with actionable instructions when the secret
            cannot be read (library missing, project undiscoverable, or the
            secret does not exist).
    """
    create_hint = (
        f"Create the secret from your kaggle.json:\n"
        f"  gcloud secrets create {secret_name} "
        f"--data-file=$HOME/.kaggle/kaggle.json\n"
        f"(download kaggle.json from https://www.kaggle.com/settings -> "
        f"'Create New Token')."
    )

    try:
        from google.cloud import secretmanager
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise KaggleCredentialsError(
            "google-cloud-secret-manager is not installed; cannot read the "
            f"'{secret_name}' secret. Install it with "
            "'pip install google-cloud-secret-manager'."
        ) from exc

    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if not project:
        try:
            import google.auth

            _, project = google.auth.default()
        except Exception as exc:  # noqa: BLE001 - best-effort project discovery
            raise KaggleCredentialsError(
                "could not determine the GCP project for Secret Manager; set "
                "GOOGLE_CLOUD_PROJECT or run 'gcloud auth application-default "
                "login'."
            ) from exc
    if not project:
        raise KaggleCredentialsError(
            "no GCP project found; set GOOGLE_CLOUD_PROJECT before running."
        )

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_name}/versions/latest"
    try:
        response = client.access_secret_version(name=name)
    except Exception as exc:  # noqa: BLE001 - surfaced with clear instructions
        raise KaggleCredentialsError(
            f"could not read Kaggle credentials from Secret Manager secret "
            f"'{secret_name}' in project '{project}': {exc}\n{create_hint}"
        ) from exc

    payload: str = response.payload.data.decode("utf-8")
    return payload


def validate_credentials(payload: str) -> None:
    """Validate that a ``kaggle.json`` payload has ``username`` and ``key``.

    Raises:
        KaggleCredentialsError: when the payload is not JSON or is missing the
            required fields.
    """
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise KaggleCredentialsError(
            "kaggle.json is not valid JSON; it must look like "
            '{"username": "<user>", "key": "<token>"}.'
        ) from exc
    if not isinstance(data, dict) or not data.get("username") or not data.get("key"):
        raise KaggleCredentialsError(
            'kaggle.json must contain non-empty "username" and "key" fields.'
        )


@contextlib.contextmanager
def kaggle_config_dir(payload: str) -> Iterator[str]:
    """Write ``kaggle.json`` to a temp dir and expose it via ``KAGGLE_CONFIG_DIR``.

    The credentials file is created ``0o600`` and the temp directory (plus the
    ``KAGGLE_CONFIG_DIR`` override) is removed on exit, even on error.
    """
    validate_credentials(payload)
    tmp_dir = tempfile.mkdtemp(prefix="kaggle-cfg-")
    previous = os.environ.get("KAGGLE_CONFIG_DIR")
    try:
        cred_path = Path(tmp_dir) / "kaggle.json"
        cred_path.write_text(payload, encoding="utf-8")
        os.chmod(cred_path, 0o600)
        os.environ["KAGGLE_CONFIG_DIR"] = tmp_dir
        yield tmp_dir
    finally:
        if previous is None:
            os.environ.pop("KAGGLE_CONFIG_DIR", None)
        else:
            os.environ["KAGGLE_CONFIG_DIR"] = previous
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────
# Default (real) download function — lazily imports the Kaggle library
# ──────────────────────────────────────────────────────────────────────────
def _default_download(dataset: str, dest_dir: str) -> None:
    """Download and unzip a Kaggle dataset into ``dest_dir`` via the kaggle lib.

    Imported inside the function so the module imports without the ``kaggle``
    package and so the import (which authenticates) happens only after
    ``KAGGLE_CONFIG_DIR`` has been set by :func:`kaggle_config_dir`.
    """
    import kaggle

    kaggle.api.dataset_download_files(dataset, path=dest_dir, unzip=True)


# ──────────────────────────────────────────────────────────────────────────
# Manifest models
# ──────────────────────────────────────────────────────────────────────────
class FileEntry(BaseModel):
    """Per-file record in the manifest."""

    filename: str
    remote_uri: str
    md5: str
    size_bytes: int
    row_count: int
    columns: list[str] = Field(default_factory=list)


class MtSamplesManifest(BaseModel):
    """Manifest written to ``<output_prefix>/_manifest.json``."""

    run_id: str
    started_at: str
    completed_at: str | None = None
    dataset: str
    output_uri: str
    status: DownloadStatus
    files: list[FileEntry] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)
    error: str | None = None


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_gs_uri(uri: str) -> tuple[str, str]:
    """Split ``gs://bucket/prefix`` into ``(bucket, prefix)``.

    The prefix may be empty (bucket root) and is returned without a trailing
    slash.
    """
    if not uri.startswith("gs://"):
        raise ValueError(f"not a gs:// URI: {uri!r}")
    without_scheme = uri[len("gs://") :]
    bucket, _, prefix = without_scheme.partition("/")
    if not bucket:
        raise ValueError(f"gs:// URI must include a bucket: {uri!r}")
    return bucket, prefix.strip("/")


def compute_md5(path: Path, chunk: int = 1024 * 1024) -> str:
    """Return the hex MD5 digest of a file."""
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def csv_stats(path: Path) -> tuple[int, list[str]]:
    """Return ``(data_row_count, header_columns)`` for a CSV file.

    The header row is excluded from the count. An empty file yields ``(0, [])``.
    """
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration:
            return 0, []
        rows = sum(1 for _ in reader)
    return rows, header


# ──────────────────────────────────────────────────────────────────────────
# Downloader
# ──────────────────────────────────────────────────────────────────────────
class MtSamplesDownloader:
    """Downloads the MTSamples Kaggle dataset to GCS, producing a manifest.

    The storage client, credential provider, and download function are injected
    so the logic can be tested against fakes without contacting GCS, Secret
    Manager, or Kaggle.
    """

    def __init__(
        self,
        client: Any,
        output_uri: str,
        dataset: str,
        *,
        force: bool = False,
        dry_run: bool = False,
        credentials_provider: CredentialsProvider | None = None,
        download_fn: DownloadFn | None = None,
    ) -> None:
        self.client = client
        self.output_uri = output_uri
        self.dataset = dataset
        self.bucket_name, self.prefix = parse_gs_uri(output_uri)
        self.bucket = client.bucket(self.bucket_name)
        self.force = force
        self.dry_run = dry_run
        # Resolve defaults at runtime (not as bound default args) so tests can
        # monkeypatch the module-level functions and main() picks them up.
        self.credentials_provider = credentials_provider or resolve_kaggle_credentials
        self.download_fn = download_fn or _default_download

    # -- path helpers -------------------------------------------------------
    def object_name(self, rel_path: str) -> str:
        return f"{self.prefix}/{rel_path}" if self.prefix else rel_path

    @property
    def manifest_object_name(self) -> str:
        return self.object_name("_manifest.json")

    def remote_uri(self, rel_path: str) -> str:
        return f"gs://{self.bucket_name}/{self.object_name(rel_path)}"

    # -- manifest IO --------------------------------------------------------
    def existing_manifest(self) -> MtSamplesManifest | None:
        blob = self.bucket.blob(self.manifest_object_name)
        if not blob.exists():
            return None
        try:
            return MtSamplesManifest.model_validate_json(blob.download_as_text())
        except Exception as exc:  # noqa: BLE001 - corrupt manifest -> re-download
            log.warning("manifest_unreadable", dataset=self.dataset, error=str(exc))
            return None

    def write_manifest(self, manifest: MtSamplesManifest) -> str:
        uri = f"gs://{self.bucket_name}/{self.manifest_object_name}"
        blob = self.bucket.blob(self.manifest_object_name)
        blob.upload_from_string(
            json.dumps(manifest.model_dump(), indent=2), content_type="application/json"
        )
        log.info("manifest_written", uri=uri)
        return uri

    # -- core ---------------------------------------------------------------
    def _upload_csvs(self, dest_dir: str, run_id: str, started_at: str) -> MtSamplesManifest:
        """Upload every CSV under ``dest_dir`` and build the manifest."""
        root = Path(dest_dir)
        csv_paths = sorted(p for p in root.rglob("*.csv") if p.is_file())
        if not csv_paths:
            raise NoCsvError(f"dataset {self.dataset!r} produced no CSV files in the download.")

        files: list[FileEntry] = []
        for path in csv_paths:
            rel_path = path.relative_to(root).as_posix()
            rows, columns = csv_stats(path)
            self.bucket.blob(self.object_name(rel_path)).upload_from_filename(str(path))
            files.append(
                FileEntry(
                    filename=rel_path,
                    remote_uri=self.remote_uri(rel_path),
                    md5=compute_md5(path),
                    size_bytes=path.stat().st_size,
                    row_count=rows,
                    columns=columns,
                )
            )

        return MtSamplesManifest(
            run_id=run_id,
            started_at=started_at,
            completed_at=_utc_now_iso(),
            dataset=self.dataset,
            output_uri=self.output_uri,
            status="downloaded",
            files=files,
            totals={
                "files": len(files),
                "total_bytes": sum(f.size_bytes for f in files),
                "total_rows": sum(f.row_count for f in files),
            },
        )

    def run(self) -> MtSamplesManifest:
        """Resolve credentials, download, upload, and write the manifest.

        Returns the manifest. Raises :class:`KaggleCredentialsError` or
        :class:`NoCsvError` on unrecoverable failures.
        """
        run_id = str(uuid.uuid4())
        started_at = _utc_now_iso()

        # Idempotency: a recorded successful download short-circuits everything
        # (no credentials needed) unless --force is given.
        if not self.force:
            existing = self.existing_manifest()
            if existing is not None and existing.status == "downloaded":
                log.info("skip_existing", dataset=self.dataset, uri=self.output_uri)
                return existing.model_copy(update={"status": "skipped"})

        if self.dry_run:
            log.info("plan_download", dataset=self.dataset, uri=self.output_uri)
            return MtSamplesManifest(
                run_id=run_id,
                started_at=started_at,
                completed_at=_utc_now_iso(),
                dataset=self.dataset,
                output_uri=self.output_uri,
                status="downloaded",
            )

        payload = self.credentials_provider()
        with kaggle_config_dir(payload):
            tmp_dir = tempfile.mkdtemp(prefix="mtsamples-dl-")
            try:
                self.download_fn(self.dataset, tmp_dir)
                manifest = self._upload_csvs(tmp_dir, run_id, started_at)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

        self.write_manifest(manifest)
        log.info(
            "downloaded",
            dataset=self.dataset,
            files=manifest.totals.get("files", 0),
            rows=manifest.totals.get("total_rows", 0),
            bytes=manifest.totals.get("total_bytes", 0),
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
        prog="download_mtsamples_kaggle",
        description="Download the MTSamples Kaggle dataset to GCS.",
    )
    parser.add_argument(
        "--output-bucket",
        required=True,
        help="GCS gs:// URI prefix for dataset output.",
    )
    parser.add_argument(
        "--dataset",
        default="tboyle10/medicaltranscriptions",
        help="Kaggle dataset slug (default: tboyle10/medicaltranscriptions).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be downloaded without downloading or writing.",
    )
    parser.add_argument("--force", action="store_true", help="Re-download even if up to date.")
    parser.add_argument("--verbose", action="store_true", help="Debug logging.")
    return parser


def print_summary(manifest: MtSamplesManifest, dry_run: bool) -> None:
    label = "DRY RUN" if dry_run else "RUN"
    print(f"\n=== MTSamples download {label} (run_id={manifest.run_id}) ===")
    if dry_run:
        verb = "would skip" if manifest.status == "skipped" else "would download"
        print(f"  {manifest.dataset}: {verb} -> {manifest.output_uri}")
        return
    rows = manifest.totals.get("total_rows", 0)
    nbytes = manifest.totals.get("total_bytes", 0)
    nfiles = manifest.totals.get("files", len(manifest.files))
    print(f"  {manifest.dataset}: {manifest.status} " f"files={nfiles} rows={rows} bytes={nbytes}")
    for entry in manifest.files:
        print(f"    - {entry.filename}: rows={entry.row_count} md5={entry.md5}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    try:
        parse_gs_uri(args.output_bucket)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    client = storage.Client()
    downloader = MtSamplesDownloader(
        client,
        args.output_bucket,
        args.dataset,
        force=args.force,
        dry_run=args.dry_run,
    )

    try:
        manifest = downloader.run()
    except KaggleCredentialsError as exc:
        log.error("kaggle_credentials_error", error=str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except NoCsvError as exc:
        log.error("no_csv", error=str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print_summary(manifest, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
