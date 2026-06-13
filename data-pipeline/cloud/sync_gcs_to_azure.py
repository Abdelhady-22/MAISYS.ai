"""Cross-cloud sync from Google Cloud Storage to Azure Blob Storage.

Phase C of the MAISYS data pipeline: every object in a GCS source prefix is
streamed (no local intermediary file) into the matching Azure Blob container,
with Content-MD5 verification on both sides. The script is idempotent — re-runs
skip files already present in Azure with a matching MD5 — and concurrent via a
thread pool sized to ``--parallel``.

Behaviour
---------
1. Authenticates to GCS via Application Default Credentials and to Azure via a
   service principal whose credentials are fetched from GCP Secret Manager
   under the secret name ``azure-service-principal``.
2. Lists every object in the source bucket under the configured prefix.
3. For each object:
     a. Computes the target Azure blob name (1:1 with the GCS object key).
     b. Skips when an Azure blob already exists with a matching MD5 (unless
        ``--force``).
     c. Otherwise streams the object: a single ``upload_blob`` for files at or
        below 100 MB, ``stage_block`` + ``commit_block_list`` for larger ones.
     d. Re-fetches the Azure Content-MD5 and compares to the source GCS MD5.
        On mismatch the upload is retried up to ``--retry-attempts`` times
        before being flagged as failed.
4. Writes a JSON run manifest to
   ``gs://<source-bucket>/manifests/sync_to_azure_<run_id>.json``.
5. Exits 0 only if every file succeeded.

Usage
-----
    python data-pipeline/cloud/sync_gcs_to_azure.py \\
        --source gs://maisys-data-dev/ \\
        --target-account maisysstage \\
        --target-container maisys-data-stage \\
        --parallel 16 \\
        [--prefix raw/] \\
        [--dry-run] [--force] [--verbose]

The GCP project used for Secret Manager is the one discovered by
``google.auth.default()`` — never hard-coded.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import ClientSecretCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from google.api_core import exceptions as gcp_exceptions
from google.auth import default as get_application_default_credentials
from google.cloud import secretmanager, storage  # type: ignore[attr-defined]
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tqdm import tqdm

log = structlog.get_logger()

AZURE_SECRET_NAME = "azure-service-principal"
CHUNKED_UPLOAD_THRESHOLD_BYTES = 100 * 1024 * 1024
DEFAULT_BLOCK_SIZE_BYTES = 8 * 1024 * 1024
DEFAULT_RETRY_ATTEMPTS = 3
MANIFEST_PREFIX = "manifests/"

FileStatus = Literal["synced", "skipped", "failed"]


# ──────────────────────────────────────────────────────────────────────────
# Config models
# ──────────────────────────────────────────────────────────────────────────
class SyncConfig(BaseModel):
    """CLI-derived sync configuration."""

    source_bucket: str = Field(min_length=1)
    source_prefix: str = ""
    target_account: str = Field(min_length=1)
    target_container: str = Field(min_length=1)
    parallel: int = Field(default=16, ge=1)
    retry_attempts: int = Field(default=DEFAULT_RETRY_ATTEMPTS, ge=1)
    block_size_bytes: int = Field(default=DEFAULT_BLOCK_SIZE_BYTES, ge=1)
    chunked_threshold_bytes: int = Field(default=CHUNKED_UPLOAD_THRESHOLD_BYTES, ge=1)
    manifest_bucket: str = Field(min_length=1)


class AzureCredentials(BaseModel):
    """Service principal credentials shape — matches the JSON in Secret Manager."""

    model_config = ConfigDict(populate_by_name=True)

    tenant_id: str = Field(alias="tenantId", min_length=1)
    client_id: str = Field(alias="clientId", min_length=1)
    client_secret: str = Field(alias="clientSecret", min_length=1)
    subscription_id: str = Field(alias="subscriptionId", min_length=1)
    storage_account: str = Field(alias="storageAccount", min_length=1)


# ──────────────────────────────────────────────────────────────────────────
# Manifest models
# ──────────────────────────────────────────────────────────────────────────
class FileEntry(BaseModel):
    """Per-file record in the manifest."""

    object_name: str
    source_uri: str
    target_uri: str
    md5: str | None
    size_bytes: int
    status: FileStatus
    attempts: int
    error: str | None = None


class Manifest(BaseModel):
    """The JSON manifest written to GCS at the end of a run."""

    run_id: str
    source: str
    target: str
    prefix: str
    started_at: str
    completed_at: str | None = None
    total_files: int = 0
    synced_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    failed_files: list[str] = Field(default_factory=list)
    files: list[FileEntry] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────────
class Md5MismatchError(Exception):
    """Raised when a post-upload Azure MD5 does not match the source GCS MD5."""


class AzureSecretMissingError(Exception):
    """Raised when the Azure service principal secret is absent from Secret Manager."""


# ──────────────────────────────────────────────────────────────────────────
# Pure helpers
# ──────────────────────────────────────────────────────────────────────────
def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_gs_uri(uri: str) -> tuple[str, str]:
    """Split a ``gs://bucket[/prefix]`` URI into ``(bucket, prefix)``.

    A bare ``gs://bucket`` or ``gs://bucket/`` returns ``("bucket", "")``.
    """
    if not uri.startswith("gs://"):
        raise ValueError(f"not a gs:// URI: {uri!r}")
    without_scheme = uri[len("gs://") :]
    bucket, _, prefix = without_scheme.partition("/")
    if not bucket:
        raise ValueError(f"gs:// URI must include a bucket: {uri!r}")
    return bucket, prefix


def join_prefix(source_prefix: str, extra: str | None) -> str:
    """Combine the path portion of ``--source`` with the optional ``--prefix``.

    Both pieces are normalised (no leading/trailing slashes). The returned
    prefix either ends with ``/`` or is empty.
    """
    parts = [p.strip("/") for p in (source_prefix, extra or "") if p and p.strip("/")]
    if not parts:
        return ""
    return "/".join(parts) + "/"


def azure_blob_url(account: str, container: str, blob_name: str) -> str:
    return f"https://{account}.blob.core.windows.net/{container}/{blob_name}"


def _format_create_secret_command(project_id: str, secret_name: str) -> str:
    """Build the gcloud command shown to the user when the secret is missing."""
    payload = (
        '{"tenantId":"<tenant>","clientId":"<client>","clientSecret":"<secret>",'
        '"subscriptionId":"<subscription>","storageAccount":"<account>"}'
    )
    return (
        f"gcloud secrets create {secret_name} "
        f"--replication-policy=automatic --project={project_id} && \\\n"
        f"    printf '%s' '{payload}' | \\\n"
        f"      gcloud secrets versions add {secret_name} "
        f"--data-file=- --project={project_id}"
    )


def fetch_azure_credentials(
    secret_client: Any, project_id: str, secret_name: str = AZURE_SECRET_NAME
) -> AzureCredentials:
    """Fetch and parse Azure service principal credentials from GCP Secret Manager.

    Raises :class:`AzureSecretMissingError` with the exact remediation command
    when the secret does not exist in the project.
    """
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    try:
        response = secret_client.access_secret_version(request={"name": name})
    except gcp_exceptions.NotFound as exc:
        remediation = _format_create_secret_command(project_id, secret_name)
        raise AzureSecretMissingError(
            f"Azure service principal secret {secret_name!r} not found in GCP project "
            f"{project_id!r}. Create it with:\n\n    {remediation}\n"
        ) from exc
    payload = response.payload.data.decode("utf-8")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Azure secret {secret_name!r} is not valid JSON: {exc}") from exc
    return AzureCredentials.model_validate(data)


def build_azure_client(creds: AzureCredentials, account: str) -> BlobServiceClient:
    """Construct a BlobServiceClient authenticated with a service principal."""
    credential = ClientSecretCredential(
        tenant_id=creds.tenant_id,
        client_id=creds.client_id,
        client_secret=creds.client_secret,
    )
    return BlobServiceClient(
        account_url=f"https://{account}.blob.core.windows.net",
        credential=credential,
    )


# ──────────────────────────────────────────────────────────────────────────
# Syncer
# ──────────────────────────────────────────────────────────────────────────
class Syncer:
    """Sync from GCS to Azure Blob, producing a manifest.

    Both clients are injected so the sync logic can be exercised against
    in-memory fakes in tests without touching live cloud services.
    """

    def __init__(
        self,
        gcs_client: Any,
        azure_service_client: Any,
        config: SyncConfig,
        *,
        force: bool = False,
        dry_run: bool = False,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.gcs = gcs_client
        self.azure = azure_service_client
        self.config = config
        self.force = force
        self.dry_run = dry_run
        self.sleep = sleep
        self.container = azure_service_client.get_container_client(config.target_container)

    # ── Listing ────────────────────────────────────────────────────────
    def list_source_objects(self) -> list[Any]:
        """List every GCS blob under the configured source prefix, sorted by name."""
        prefix = self.config.source_prefix or None
        blobs = list(self.gcs.list_blobs(self.config.source_bucket, prefix=prefix))
        return sorted(blobs, key=lambda b: b.name)

    # ── Azure introspection ────────────────────────────────────────────
    def azure_blob_md5(self, blob_name: str) -> str | None:
        """Return the base64 MD5 of an existing Azure blob, or ``None`` if absent."""
        blob_client = self.container.get_blob_client(blob_name)
        try:
            props = blob_client.get_blob_properties()
        except ResourceNotFoundError:
            return None
        md5_bytes = props.content_settings.content_md5
        if md5_bytes is None:
            return None
        return base64.b64encode(bytes(md5_bytes)).decode("ascii")

    # ── Upload primitives ──────────────────────────────────────────────
    def _upload_small(self, source_blob: Any, target_blob_client: Any, md5_b64: str) -> None:
        """Single-shot upload via ``download_as_bytes`` + ``upload_blob``."""
        data = source_blob.download_as_bytes()
        md5_bytes = base64.b64decode(md5_b64)
        target_blob_client.upload_blob(
            data,
            overwrite=True,
            content_settings=ContentSettings(content_md5=bytearray(md5_bytes)),
        )

    def _upload_chunked(
        self,
        source_blob: Any,
        target_blob_client: Any,
        md5_b64: str,
        size_bytes: int,
    ) -> None:
        """Streaming upload via ``stage_block`` + ``commit_block_list``.

        Each block is downloaded as a byte range from GCS and immediately staged
        to Azure, so total resident memory stays bounded by ``block_size_bytes``.
        """
        block_ids: list[str] = []
        block_size = self.config.block_size_bytes
        offset = 0
        index = 0
        while offset < size_bytes:
            end = min(offset + block_size, size_bytes) - 1
            chunk = source_blob.download_as_bytes(start=offset, end=end)
            block_id = base64.b64encode(f"block-{index:08d}".encode("ascii")).decode("ascii")
            target_blob_client.stage_block(block_id=block_id, data=chunk)
            block_ids.append(block_id)
            offset = end + 1
            index += 1
        md5_bytes = base64.b64decode(md5_b64)
        target_blob_client.commit_block_list(
            block_ids,
            content_settings=ContentSettings(content_md5=bytearray(md5_bytes)),
        )

    # ── Per-file orchestration ─────────────────────────────────────────
    def sync_one(self, source_blob: Any) -> FileEntry:
        """Sync one GCS blob to Azure with retry on MD5 mismatch or upload failure."""
        object_name: str = source_blob.name
        source_uri = f"gs://{self.config.source_bucket}/{object_name}"
        target_uri = azure_blob_url(
            self.config.target_account, self.config.target_container, object_name
        )
        gcs_md5_b64: str | None = source_blob.md5_hash
        size_bytes = int(source_blob.size or 0)

        def entry(status: FileStatus, attempts: int, error: str | None = None) -> FileEntry:
            return FileEntry(
                object_name=object_name,
                source_uri=source_uri,
                target_uri=target_uri,
                md5=gcs_md5_b64,
                size_bytes=size_bytes,
                status=status,
                attempts=attempts,
                error=error,
            )

        # Integrity verification is mandatory: refuse to copy a source without an MD5.
        if gcs_md5_b64 is None:
            log.warning("source_md5_missing", source=source_uri)
            return entry(
                "failed",
                attempts=0,
                error="source GCS object has no MD5; refusing to upload without verification",
            )

        # Resume: skip if Azure already holds a matching MD5.
        if not self.force:
            existing = self.azure_blob_md5(object_name)
            if existing == gcs_md5_b64:
                log.debug("skip_match", source=source_uri, target=target_uri)
                return entry("skipped", attempts=0)

        if self.dry_run:
            log.info("plan_sync", source=source_uri, target=target_uri, size_bytes=size_bytes)
            return entry("synced", attempts=0)

        target_blob_client = self.container.get_blob_client(object_name)
        last_error: str | None = None
        for attempt in range(self.config.retry_attempts):
            try:
                if size_bytes > self.config.chunked_threshold_bytes:
                    self._upload_chunked(source_blob, target_blob_client, gcs_md5_b64, size_bytes)
                else:
                    self._upload_small(source_blob, target_blob_client, gcs_md5_b64)
                uploaded_md5 = self.azure_blob_md5(object_name)
                if uploaded_md5 != gcs_md5_b64:
                    raise Md5MismatchError(
                        f"{target_uri}: post-upload MD5 {uploaded_md5!r} "
                        f"!= source {gcs_md5_b64!r}"
                    )
                log.debug("synced", source=source_uri, target=target_uri, attempt=attempt + 1)
                return entry("synced", attempts=attempt + 1)
            except Exception as exc:  # noqa: BLE001 - recorded and retried
                last_error = str(exc)
                log.warning(
                    "sync_failed",
                    source=source_uri,
                    target=target_uri,
                    attempt=attempt + 1,
                    error=last_error,
                )
                if attempt < self.config.retry_attempts - 1:
                    self.sleep(2.0**attempt)

        return entry("failed", attempts=self.config.retry_attempts, error=last_error)

    # ── Whole-run orchestration ────────────────────────────────────────
    def run(self) -> Manifest:
        """List, sync every object, and assemble (but do not yet write) the manifest."""
        source_uri = f"gs://{self.config.source_bucket}/{self.config.source_prefix}"
        target_uri = (
            f"https://{self.config.target_account}.blob.core.windows.net/"
            f"{self.config.target_container}/"
        )
        manifest = Manifest(
            run_id=str(uuid.uuid4()),
            source=source_uri,
            target=target_uri,
            prefix=self.config.source_prefix,
            started_at=_utc_now_iso(),
        )

        blobs = self.list_source_objects()
        manifest.total_files = len(blobs)
        log.info("sync_start", total_files=len(blobs), prefix=self.config.source_prefix)

        if not blobs:
            manifest.completed_at = _utc_now_iso()
            return manifest

        with (
            tqdm(total=len(blobs), desc="overall", unit="file") as overall,
            ThreadPoolExecutor(max_workers=self.config.parallel) as pool,
        ):
            futures: dict[Future[FileEntry], Any] = {
                pool.submit(self.sync_one, b): b for b in blobs
            }
            for future in as_completed(futures):
                result = future.result()
                manifest.files.append(result)
                if result.status == "synced":
                    manifest.synced_count += 1
                elif result.status == "skipped":
                    manifest.skipped_count += 1
                else:
                    manifest.failed_count += 1
                    manifest.failed_files.append(result.object_name)
                overall.update(1)

        manifest.files.sort(key=lambda e: e.object_name)
        manifest.failed_files.sort()
        manifest.completed_at = _utc_now_iso()
        log.info(
            "sync_done",
            total=manifest.total_files,
            synced=manifest.synced_count,
            skipped=manifest.skipped_count,
            failed=manifest.failed_count,
        )
        return manifest

    def write_manifest(self, manifest: Manifest) -> str:
        """Upload the manifest JSON to ``gs://<manifest_bucket>/manifests/...``."""
        object_name = f"{MANIFEST_PREFIX}sync_to_azure_{manifest.run_id}.json"
        payload = json.dumps(manifest.model_dump(), indent=2, sort_keys=False)
        blob = self.gcs.bucket(self.config.manifest_bucket).blob(object_name)
        blob.upload_from_string(payload, content_type="application/json")
        uri = f"gs://{self.config.manifest_bucket}/{object_name}"
        log.info("manifest_written", uri=uri)
        return uri


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
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
        prog="sync_gcs_to_azure",
        description="Cross-cloud sync from a GCS bucket to an Azure Blob container.",
    )
    parser.add_argument(
        "--source", required=True, help="Source GCS URI, e.g. gs://maisys-data-dev/"
    )
    parser.add_argument("--target-account", required=True, help="Azure storage account name.")
    parser.add_argument("--target-container", required=True, help="Azure blob container name.")
    parser.add_argument(
        "--parallel", type=int, default=16, help="Concurrent transfers (default: 16)."
    )
    parser.add_argument("--prefix", default=None, help="Optional GCS prefix narrowing (e.g. raw/).")
    parser.add_argument(
        "--retry-attempts",
        type=int,
        default=DEFAULT_RETRY_ATTEMPTS,
        help=f"Per-file retry attempts (default: {DEFAULT_RETRY_ATTEMPTS}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned syncs without uploading or writing a manifest.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-sync every file even if Azure already holds a matching MD5.",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug-level logging.")
    return parser


def print_summary(manifest: Manifest, dry_run: bool) -> None:
    """Print a single-block run summary plus the (truncated) list of failed files."""
    label = "DRY RUN" if dry_run else "RUN"
    print(f"\n=== {label} summary (run_id={manifest.run_id}) ===")
    print(f"  source: {manifest.source}")
    print(f"  target: {manifest.target}")
    verb = "would sync" if dry_run else "synced"
    print(
        f"  total={manifest.total_files} {verb}={manifest.synced_count} "
        f"skipped={manifest.skipped_count} failed={manifest.failed_count}"
    )
    if manifest.failed_files:
        print("  failed files:")
        for name in manifest.failed_files[:20]:
            print(f"    - {name}")
        remaining = len(manifest.failed_files) - 20
        if remaining > 0:
            print(f"    ... and {remaining} more")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    if args.parallel < 1:
        print("Config error: --parallel must be >= 1", file=sys.stderr)
        return 2
    if args.retry_attempts < 1:
        print("Config error: --retry-attempts must be >= 1", file=sys.stderr)
        return 2

    try:
        source_bucket, source_prefix = parse_gs_uri(args.source)
    except ValueError as exc:
        log.error("source_uri_invalid", error=str(exc))
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    effective_prefix = join_prefix(source_prefix, args.prefix)

    try:
        credentials, project_id = get_application_default_credentials()
    except Exception as exc:  # noqa: BLE001 - reported to user
        log.error("gcp_auth_failed", error=str(exc))
        print(f"GCP authentication failed: {exc}", file=sys.stderr)
        return 2
    if not project_id:
        print(
            "Could not determine GCP project from Application Default Credentials. "
            "Run `gcloud config set project <project>` or set GOOGLE_CLOUD_PROJECT.",
            file=sys.stderr,
        )
        return 2

    secret_client = secretmanager.SecretManagerServiceClient(credentials=credentials)
    try:
        azure_creds = fetch_azure_credentials(secret_client, project_id)
    except AzureSecretMissingError as exc:
        log.error("azure_secret_missing", error=str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, ValidationError) as exc:
        log.error("azure_secret_invalid", error=str(exc))
        print(f"Error: Azure secret payload invalid: {exc}", file=sys.stderr)
        return 2

    config = SyncConfig(
        source_bucket=source_bucket,
        source_prefix=effective_prefix,
        target_account=args.target_account,
        target_container=args.target_container,
        parallel=args.parallel,
        retry_attempts=args.retry_attempts,
        manifest_bucket=source_bucket,
    )

    gcs_client = storage.Client(project=project_id, credentials=credentials)
    azure_client = build_azure_client(azure_creds, args.target_account)

    syncer = Syncer(gcs_client, azure_client, config, force=args.force, dry_run=args.dry_run)
    manifest = syncer.run()

    if not args.dry_run:
        syncer.write_manifest(manifest)

    print_summary(manifest, args.dry_run)

    if manifest.failed_count > 0:
        print(f"\n{manifest.failed_count} file(s) failed to sync.", file=sys.stderr)
        return 1
    return 0


# Public API surface — names callers and tests import from this module.
__all__ = [
    "AzureCredentials",
    "AzureSecretMissingError",
    "FileEntry",
    "Manifest",
    "Md5MismatchError",
    "SyncConfig",
    "Syncer",
    "azure_blob_url",
    "build_azure_client",
    "fetch_azure_credentials",
    "join_prefix",
    "main",
    "parse_gs_uri",
]


if __name__ == "__main__":
    raise SystemExit(main())
