"""Cross-cloud sync from Google Cloud Storage to AWS S3.

Phase C of the MAISYS data pipeline: every object in a GCS source prefix is
streamed (no local intermediary file) into the matching S3 bucket, with
integrity verification on both sides. The script is idempotent — re-runs skip
files already present in S3 with a matching MD5 — and concurrent via a thread
pool sized to ``--parallel``.

S3 ETag quirks
--------------
S3's ETag is not always the object's MD5:

* For single-part uploads (``put_object``), ETag == lowercase hex MD5 of the
  object bytes.
* For multipart uploads, ETag == ``<hex(md5(concat(part_md5s)))>-<num_parts>``
  — a digest of the per-part MD5s, with the part count appended.

Verification therefore branches on whether the ETag contains a dash. For our
own uploads we always know which path was taken, so we either compare hex MD5s
directly or recompute the multipart-style hash from the part MD5s we tracked
during upload. For the skip-if-exists check on an existing S3 object whose
ETag has a dash, we conservatively re-upload — confirming a multipart object
without re-downloading the source would require knowing the chunk size used
for the prior upload, which is not stored in object metadata.

Behaviour
---------
1. Authenticates to GCS via Application Default Credentials and to AWS via
   credentials fetched from GCP Secret Manager under the secret name
   ``aws-credentials``.
2. Lists every object in the source bucket under the configured prefix.
3. For each object:
     a. Computes the target S3 key (1:1 with the GCS object key).
     b. Skips when an S3 object already exists with a matching MD5 (unless
        ``--force``); a multipart ETag on the existing object falls through
        to re-upload.
     c. Otherwise streams the object: a single ``put_object`` for files at
        or below 100 MB, ``create_multipart_upload`` + ``upload_part`` +
        ``complete_multipart_upload`` for larger ones.
     d. Re-fetches the S3 ETag and verifies it against the expected value
        (hex MD5 for single-part, computed multipart hash for multipart).
        On mismatch the upload is retried up to ``--retry-attempts`` times
        before being flagged as failed.
4. Writes a JSON run manifest to
   ``gs://<source-bucket>/manifests/sync_to_aws_<run_id>.json``.
5. Exits 0 only if every file succeeded.

Usage
-----
    python data-pipeline/cloud/sync_gcs_to_aws.py \\
        --source gs://maisys-data-dev/ \\
        --target-bucket maisys-data-prod \\
        --parallel 16 \\
        [--prefix raw/] \\
        [--dry-run] [--force] [--verbose]

The GCP project used for Secret Manager is the one discovered by
``google.auth.default()`` — never hard-coded.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any, Literal

import boto3
import structlog
from botocore.exceptions import ClientError
from google.api_core import exceptions as gcp_exceptions
from google.auth import default as get_application_default_credentials
from google.cloud import secretmanager, storage  # type: ignore[attr-defined]
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tqdm import tqdm

log = structlog.get_logger()

AWS_SECRET_NAME = "aws-credentials"
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
    target_bucket: str = Field(min_length=1)
    parallel: int = Field(default=16, ge=1)
    retry_attempts: int = Field(default=DEFAULT_RETRY_ATTEMPTS, ge=1)
    block_size_bytes: int = Field(default=DEFAULT_BLOCK_SIZE_BYTES, ge=1)
    chunked_threshold_bytes: int = Field(default=CHUNKED_UPLOAD_THRESHOLD_BYTES, ge=1)
    manifest_bucket: str = Field(min_length=1)


class AwsCredentials(BaseModel):
    """AWS credentials shape — matches the JSON in Secret Manager."""

    model_config = ConfigDict(populate_by_name=True)

    access_key_id: str = Field(alias="accessKeyId", min_length=1)
    secret_access_key: str = Field(alias="secretAccessKey", min_length=1)
    region: str = Field(min_length=1)
    bucket: str = Field(min_length=1)


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
class EtagMismatchError(Exception):
    """Raised when a post-upload S3 ETag does not match the expected value."""


class AwsSecretMissingError(Exception):
    """Raised when the AWS credentials secret is absent from Secret Manager."""


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


def s3_object_url(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def strip_etag_quotes(etag: str) -> str:
    """Strip the surrounding double quotes S3 wraps every ETag in."""
    return etag.strip('"')


def is_multipart_etag(etag: str) -> bool:
    """Return True if the (unquoted) ETag is a multipart digest (``<md5>-<N>``)."""
    return "-" in etag


def compute_multipart_etag(part_md5_digests: list[bytes], num_parts: int) -> str:
    """Compute the S3 multipart ETag from raw per-part MD5 digests.

    The S3 algorithm is ``hex(md5(concat(part_md5s))) + "-" + str(num_parts)``.
    ``part_md5_digests`` must contain the raw 16-byte digests in the same
    order parts were uploaded.
    """
    concatenated = b"".join(part_md5_digests)
    return f"{hashlib.md5(concatenated).hexdigest()}-{num_parts}"


def _format_create_secret_command(project_id: str, secret_name: str) -> str:
    """Build the gcloud command shown to the user when the secret is missing."""
    payload = (
        '{"accessKeyId":"<key>","secretAccessKey":"<secret>",'
        '"region":"us-east-1","bucket":"<bucket>"}'
    )
    return (
        f"gcloud secrets create {secret_name} "
        f"--replication-policy=automatic --project={project_id} && \\\n"
        f"    printf '%s' '{payload}' | \\\n"
        f"      gcloud secrets versions add {secret_name} "
        f"--data-file=- --project={project_id}"
    )


def fetch_aws_credentials(
    secret_client: Any, project_id: str, secret_name: str = AWS_SECRET_NAME
) -> AwsCredentials:
    """Fetch and parse AWS credentials from GCP Secret Manager.

    Raises :class:`AwsSecretMissingError` with the exact remediation command
    when the secret does not exist in the project.
    """
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    try:
        response = secret_client.access_secret_version(request={"name": name})
    except gcp_exceptions.NotFound as exc:
        remediation = _format_create_secret_command(project_id, secret_name)
        raise AwsSecretMissingError(
            f"AWS credentials secret {secret_name!r} not found in GCP project "
            f"{project_id!r}. Create it with:\n\n    {remediation}\n"
        ) from exc
    payload = response.payload.data.decode("utf-8")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AWS secret {secret_name!r} is not valid JSON: {exc}") from exc
    return AwsCredentials.model_validate(data)


def build_aws_client(creds: AwsCredentials) -> Any:
    """Construct a boto3 S3 client using credentials from Secret Manager."""
    session = boto3.Session(
        aws_access_key_id=creds.access_key_id,
        aws_secret_access_key=creds.secret_access_key,
        region_name=creds.region,
    )
    return session.client("s3")


# ──────────────────────────────────────────────────────────────────────────
# Syncer
# ──────────────────────────────────────────────────────────────────────────
class Syncer:
    """Sync from GCS to AWS S3, producing a manifest.

    Both clients are injected so the sync logic can be exercised against
    in-memory fakes in tests without touching live cloud services.
    """

    def __init__(
        self,
        gcs_client: Any,
        s3_client: Any,
        config: SyncConfig,
        *,
        force: bool = False,
        dry_run: bool = False,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.gcs = gcs_client
        self.s3 = s3_client
        self.config = config
        self.force = force
        self.dry_run = dry_run
        self.sleep = sleep

    # ── Listing ────────────────────────────────────────────────────────
    def list_source_objects(self) -> list[Any]:
        """List every GCS blob under the configured source prefix, sorted by name."""
        prefix = self.config.source_prefix or None
        blobs = list(self.gcs.list_blobs(self.config.source_bucket, prefix=prefix))
        return sorted(blobs, key=lambda b: b.name)

    # ── S3 introspection ───────────────────────────────────────────────
    def s3_object_etag(self, key: str) -> str | None:
        """Return the unquoted ETag of an existing S3 object, or ``None`` if absent."""
        try:
            response = self.s3.head_object(Bucket=self.config.target_bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        etag: str = response["ETag"]
        return strip_etag_quotes(etag)

    def _should_skip(self, key: str, gcs_md5_hex: str) -> bool:
        """Return True iff S3 already holds the matching content (skip-if-exists)."""
        existing = self.s3_object_etag(key)
        if existing is None:
            return False
        if is_multipart_etag(existing):
            # Multipart ETag — without the original chunk size and per-part MD5s
            # we cannot verify a match without re-downloading the source. Be
            # conservative and re-upload; post-upload verification will catch
            # any real corruption.
            return False
        return existing.lower() == gcs_md5_hex.lower()

    # ── Upload primitives ──────────────────────────────────────────────
    def _upload_small(self, source_blob: Any, key: str, md5_b64: str) -> str:
        """Single-shot upload via ``put_object``; returns the new S3 ETag."""
        data = source_blob.download_as_bytes()
        response = self.s3.put_object(
            Bucket=self.config.target_bucket,
            Key=key,
            Body=data,
            ContentMD5=md5_b64,
        )
        etag: str = response["ETag"]
        return strip_etag_quotes(etag)

    def _upload_chunked(
        self,
        source_blob: Any,
        key: str,
        size_bytes: int,
    ) -> tuple[str, str]:
        """Streaming multipart upload.

        Returns ``(actual_etag, expected_etag)``. ``expected_etag`` is the value
        the caller should see if every part's bytes survived intact end-to-end.
        """
        create = self.s3.create_multipart_upload(Bucket=self.config.target_bucket, Key=key)
        upload_id = create["UploadId"]
        parts: list[dict[str, Any]] = []
        part_md5_digests: list[bytes] = []
        block_size = self.config.block_size_bytes
        offset = 0
        index = 0
        try:
            while offset < size_bytes:
                end = min(offset + block_size, size_bytes) - 1
                chunk = source_blob.download_as_bytes(start=offset, end=end)
                part_md5 = hashlib.md5(chunk).digest()
                part_md5_digests.append(part_md5)
                response = self.s3.upload_part(
                    Bucket=self.config.target_bucket,
                    Key=key,
                    PartNumber=index + 1,
                    UploadId=upload_id,
                    Body=chunk,
                    ContentMD5=base64.b64encode(part_md5).decode("ascii"),
                )
                parts.append({"PartNumber": index + 1, "ETag": response["ETag"]})
                offset = end + 1
                index += 1
            complete = self.s3.complete_multipart_upload(
                Bucket=self.config.target_bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": parts},
            )
        except Exception:
            # Don't leave orphaned parts billing forever.
            try:
                self.s3.abort_multipart_upload(
                    Bucket=self.config.target_bucket, Key=key, UploadId=upload_id
                )
            except Exception:  # noqa: BLE001 - best-effort cleanup
                log.warning("multipart_abort_failed", key=key, upload_id=upload_id)
            raise
        actual_etag = strip_etag_quotes(complete["ETag"])
        expected_etag = compute_multipart_etag(part_md5_digests, len(part_md5_digests))
        return actual_etag, expected_etag

    # ── Per-file orchestration ─────────────────────────────────────────
    def sync_one(self, source_blob: Any) -> FileEntry:
        """Sync one GCS blob to S3 with retry on ETag mismatch or upload failure."""
        object_name: str = source_blob.name
        source_uri = f"gs://{self.config.source_bucket}/{object_name}"
        target_uri = s3_object_url(self.config.target_bucket, object_name)
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

        gcs_md5_hex = base64.b64decode(gcs_md5_b64).hex()

        # Resume: skip if S3 already holds a matching object (single-part ETag only).
        if not self.force and self._should_skip(object_name, gcs_md5_hex):
            log.debug("skip_match", source=source_uri, target=target_uri)
            return entry("skipped", attempts=0)

        if self.dry_run:
            log.info("plan_sync", source=source_uri, target=target_uri, size_bytes=size_bytes)
            return entry("synced", attempts=0)

        last_error: str | None = None
        for attempt in range(self.config.retry_attempts):
            try:
                if size_bytes > self.config.chunked_threshold_bytes:
                    actual, expected = self._upload_chunked(source_blob, object_name, size_bytes)
                    if actual != expected:
                        raise EtagMismatchError(
                            f"{target_uri}: post-upload ETag {actual!r} "
                            f"!= expected {expected!r}"
                        )
                else:
                    actual = self._upload_small(source_blob, object_name, gcs_md5_b64)
                    # For single-part the verification can be a fresh head_object
                    # (catches any post-upload tampering, and also handles the
                    # corrupted-store case where put_object's response ETag and
                    # the stored ETag would disagree).
                    stored = self.s3_object_etag(object_name)
                    if stored is None or stored.lower() != gcs_md5_hex.lower():
                        raise EtagMismatchError(
                            f"{target_uri}: stored ETag {stored!r} "
                            f"!= source MD5 hex {gcs_md5_hex!r}"
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
        target_uri = f"s3://{self.config.target_bucket}/"
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
        object_name = f"{MANIFEST_PREFIX}sync_to_aws_{manifest.run_id}.json"
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
        prog="sync_gcs_to_aws",
        description="Cross-cloud sync from a GCS bucket to an AWS S3 bucket.",
    )
    parser.add_argument(
        "--source", required=True, help="Source GCS URI, e.g. gs://maisys-data-dev/"
    )
    parser.add_argument("--target-bucket", required=True, help="Target S3 bucket name.")
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
        help="Re-sync every file even if S3 already holds a matching MD5.",
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
        aws_creds = fetch_aws_credentials(secret_client, project_id)
    except AwsSecretMissingError as exc:
        log.error("aws_secret_missing", error=str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, ValidationError) as exc:
        log.error("aws_secret_invalid", error=str(exc))
        print(f"Error: AWS secret payload invalid: {exc}", file=sys.stderr)
        return 2

    config = SyncConfig(
        source_bucket=source_bucket,
        source_prefix=effective_prefix,
        target_bucket=args.target_bucket,
        parallel=args.parallel,
        retry_attempts=args.retry_attempts,
        manifest_bucket=source_bucket,
    )

    gcs_client = storage.Client(project=project_id, credentials=credentials)
    s3_client = build_aws_client(aws_creds)

    syncer = Syncer(gcs_client, s3_client, config, force=args.force, dry_run=args.dry_run)
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
    "AwsCredentials",
    "AwsSecretMissingError",
    "EtagMismatchError",
    "FileEntry",
    "Manifest",
    "SyncConfig",
    "Syncer",
    "build_aws_client",
    "compute_multipart_etag",
    "fetch_aws_credentials",
    "is_multipart_etag",
    "join_prefix",
    "main",
    "parse_gs_uri",
    "s3_object_url",
    "strip_etag_quotes",
]


if __name__ == "__main__":
    raise SystemExit(main())
