"""Three-way cross-cloud parity verification.

Phase C tail: after ``sync_gcs_to_azure`` and ``sync_gcs_to_aws`` complete,
this script samples (or exhaustively walks) the GCS source prefix and verifies
that each object also exists with a matching checksum in the Azure stage
container and the AWS prod bucket.

GCS is the canonical source — only objects present in GCS are checked. For
each, the script fetches:

* the GCS object MD5 (base64, from ``blob.md5_hash``),
* the Azure blob MD5 (base64, from ``content_settings.content_md5``),
* the S3 object ETag (hex, from ``head_object``).

S3 ETag quirks
--------------
S3 single-part uploads produce ``ETag == hex(MD5)`` of the object bytes.
Multipart uploads produce ``ETag == "<hex(md5(concat(part_md5s)))>-<num_parts>"``
— *not* the object's MD5. For multipart objects we cannot verify content
against GCS without re-downloading the source (the chunk size used during
upload is not stored as metadata), so we mark them ``multipart_unverifiable``
in the report rather than failing the run. Operators can either accept this
status, or re-run with metadata-based verification once that machinery exists.

Behaviour
---------
1. Authenticates to GCS via Application Default Credentials, to Azure via a
   service principal whose credentials live in GCP Secret Manager under
   ``azure-service-principal``, and to AWS via credentials in GCP Secret
   Manager under ``aws-credentials``.
2. Lists every object in the GCS source bucket under the configured prefix.
3. If ``--sample-size N`` is given and the listing exceeds ``N``, draws a
   uniform random sample of size ``N``; otherwise checks every object.
4. For each selected object, concurrently fetches Azure MD5 and AWS ETag,
   then determines the per-object status (priority: missing → mismatch →
   multipart_unverifiable → all_match).
5. Writes a JSON report to ``--output`` (defaults to
   ``gs://<gcs-bucket>/manifests/checksum_verify_<run_id>.json``).
6. Exits 0 only if every object had status ``all_match``; otherwise exits 1
   with a one-line summary to stderr.

Usage
-----
    python data-pipeline/cloud/verify_checksums.py \\
        --gcs-bucket maisys-data-dev \\
        --azure-account maisysstage \\
        --azure-container maisys-data-stage \\
        --aws-bucket maisys-data-prod \\
        [--prefix raw/] \\
        [--sample-size 5000] \\
        [--output gs://maisys-data-dev/manifests/checksum_verify_<run_id>.json] \\
        [--verbose]

The GCP project used for Secret Manager is the one discovered by
``google.auth.default()`` — never hard-coded.
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any, Literal

import boto3
import structlog
from azure.core.exceptions import ResourceNotFoundError
from azure.identity import ClientSecretCredential
from azure.storage.blob import BlobServiceClient
from botocore.exceptions import ClientError
from google.api_core import exceptions as gcp_exceptions
from google.auth import default as get_application_default_credentials
from google.cloud import secretmanager, storage  # type: ignore[attr-defined]
from pydantic import BaseModel, ConfigDict, Field, ValidationError

log = structlog.get_logger()

AZURE_SECRET_NAME = "azure-service-principal"
AWS_SECRET_NAME = "aws-credentials"
DEFAULT_PARALLEL = 32

CheckStatus = Literal[
    "all_match",
    "azure_mismatch",
    "aws_mismatch",
    "azure_missing",
    "aws_missing",
    "multipart_unverifiable",
]


# ──────────────────────────────────────────────────────────────────────────
# Config models
# ──────────────────────────────────────────────────────────────────────────
class VerifyConfig(BaseModel):
    """CLI-derived verification configuration."""

    gcs_bucket: str = Field(min_length=1)
    azure_account: str = Field(min_length=1)
    azure_container: str = Field(min_length=1)
    aws_bucket: str = Field(min_length=1)
    prefix: str = ""
    sample_size: int | None = Field(default=None, ge=1)
    parallel: int = Field(default=DEFAULT_PARALLEL, ge=1)
    output_uri: str = Field(min_length=1)


class AzureCredentials(BaseModel):
    """Azure service principal credentials shape (from GCP Secret Manager)."""

    model_config = ConfigDict(populate_by_name=True)

    tenant_id: str = Field(alias="tenantId", min_length=1)
    client_id: str = Field(alias="clientId", min_length=1)
    client_secret: str = Field(alias="clientSecret", min_length=1)
    subscription_id: str = Field(alias="subscriptionId", min_length=1)
    storage_account: str = Field(alias="storageAccount", min_length=1)


class AwsCredentials(BaseModel):
    """AWS credentials shape (from GCP Secret Manager)."""

    model_config = ConfigDict(populate_by_name=True)

    access_key_id: str = Field(alias="accessKeyId", min_length=1)
    secret_access_key: str = Field(alias="secretAccessKey", min_length=1)
    region: str = Field(min_length=1)
    bucket: str = Field(min_length=1)


# ──────────────────────────────────────────────────────────────────────────
# Report models
# ──────────────────────────────────────────────────────────────────────────
class CheckEntry(BaseModel):
    """Per-object record in the report.

    ``aws_md5`` is the raw S3 ETag — hex for single-part objects,
    ``<hex>-<N>`` for multipart objects, ``None`` if the object is absent.
    """

    gcs_path: str
    gcs_md5: str | None  # base64
    azure_md5: str | None  # base64
    aws_md5: str | None  # hex (single-part) OR <hex>-<N> (multipart)
    status: CheckStatus


class Report(BaseModel):
    """The JSON report written to GCS at the end of a run."""

    run_id: str
    started_at: str
    completed_at: str | None = None
    gcs_bucket: str
    azure_container: str
    aws_bucket: str
    prefix: str
    total_objects_checked: int = 0
    sample_size_used: int = 0
    matching_count: int = 0
    mismatch_count: int = 0
    missing_in_azure_count: int = 0
    missing_in_aws_count: int = 0
    # ``missing_in_gcs_count`` is reserved by the spec for future symmetry; under
    # the GCS-canonical model (we only list GCS) it is always 0.
    missing_in_gcs_count: int = 0
    multipart_unverifiable_count: int = 0
    mismatches: list[CheckEntry] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────
# Exceptions
# ──────────────────────────────────────────────────────────────────────────
class SecretMissingError(Exception):
    """Raised when a required cloud-credentials secret is absent from Secret Manager."""


# ──────────────────────────────────────────────────────────────────────────
# Pure helpers
# ──────────────────────────────────────────────────────────────────────────
def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_gs_uri(uri: str) -> tuple[str, str]:
    """Split a ``gs://bucket/object`` URI into ``(bucket, object_name)``."""
    if not uri.startswith("gs://"):
        raise ValueError(f"not a gs:// URI: {uri!r}")
    without_scheme = uri[len("gs://") :]
    bucket, _, object_name = without_scheme.partition("/")
    if not bucket or not object_name:
        raise ValueError(f"gs:// URI must include a bucket and object path: {uri!r}")
    return bucket, object_name


def strip_etag_quotes(etag: str) -> str:
    """Strip the surrounding double quotes S3 wraps every ETag in."""
    return etag.strip('"')


def is_multipart_etag(etag: str) -> bool:
    """Return True if the (unquoted) ETag is a multipart digest (``<md5>-<N>``)."""
    return "-" in etag


def b64_md5_to_hex(b64: str) -> str:
    """Convert a base64-encoded MD5 to its lowercase hex form."""
    return base64.b64decode(b64).hex()


def _format_create_secret_command(project_id: str, secret_name: str, payload_template: str) -> str:
    """Build a gcloud command shown to the user when a secret is missing."""
    return (
        f"gcloud secrets create {secret_name} "
        f"--replication-policy=automatic --project={project_id} && \\\n"
        f"    printf '%s' '{payload_template}' | \\\n"
        f"      gcloud secrets versions add {secret_name} "
        f"--data-file=- --project={project_id}"
    )


def fetch_azure_credentials(
    secret_client: Any, project_id: str, secret_name: str = AZURE_SECRET_NAME
) -> AzureCredentials:
    """Fetch and parse Azure service principal credentials from GCP Secret Manager."""
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    try:
        response = secret_client.access_secret_version(request={"name": name})
    except gcp_exceptions.NotFound as exc:
        payload = (
            '{"tenantId":"<tenant>","clientId":"<client>","clientSecret":"<secret>",'
            '"subscriptionId":"<subscription>","storageAccount":"<account>"}'
        )
        remediation = _format_create_secret_command(project_id, secret_name, payload)
        raise SecretMissingError(
            f"Azure service principal secret {secret_name!r} not found in GCP project "
            f"{project_id!r}. Create it with:\n\n    {remediation}\n"
        ) from exc
    data = response.payload.data.decode("utf-8")
    try:
        return AzureCredentials.model_validate(json.loads(data))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Azure secret {secret_name!r} is not valid JSON: {exc}") from exc


def fetch_aws_credentials(
    secret_client: Any, project_id: str, secret_name: str = AWS_SECRET_NAME
) -> AwsCredentials:
    """Fetch and parse AWS credentials from GCP Secret Manager."""
    name = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    try:
        response = secret_client.access_secret_version(request={"name": name})
    except gcp_exceptions.NotFound as exc:
        payload = (
            '{"accessKeyId":"<key>","secretAccessKey":"<secret>",'
            '"region":"us-east-1","bucket":"<bucket>"}'
        )
        remediation = _format_create_secret_command(project_id, secret_name, payload)
        raise SecretMissingError(
            f"AWS credentials secret {secret_name!r} not found in GCP project "
            f"{project_id!r}. Create it with:\n\n    {remediation}\n"
        ) from exc
    data = response.payload.data.decode("utf-8")
    try:
        return AwsCredentials.model_validate(json.loads(data))
    except json.JSONDecodeError as exc:
        raise ValueError(f"AWS secret {secret_name!r} is not valid JSON: {exc}") from exc


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


def build_aws_client(creds: AwsCredentials) -> Any:
    """Construct a boto3 S3 client from credentials in Secret Manager."""
    session = boto3.Session(
        aws_access_key_id=creds.access_key_id,
        aws_secret_access_key=creds.secret_access_key,
        region_name=creds.region,
    )
    return session.client("s3")


# ──────────────────────────────────────────────────────────────────────────
# Verifier
# ──────────────────────────────────────────────────────────────────────────
class Verifier:
    """Three-way checksum verifier (GCS canonical → Azure, AWS).

    All three clients are injected so the verification logic can be exercised
    against in-memory fakes in tests without touching live cloud services.
    """

    def __init__(
        self,
        gcs_client: Any,
        azure_service_client: Any,
        s3_client: Any,
        config: VerifyConfig,
        *,
        random_instance: random.Random | None = None,
    ) -> None:
        self.gcs = gcs_client
        self.azure = azure_service_client
        self.s3 = s3_client
        self.config = config
        self.random = random_instance or random.Random()
        self.container = azure_service_client.get_container_client(config.azure_container)

    # ── Listing & sampling ─────────────────────────────────────────────
    def list_source_objects(self) -> list[Any]:
        """List every GCS blob under the configured prefix, sorted by name."""
        prefix = self.config.prefix or None
        blobs = list(self.gcs.list_blobs(self.config.gcs_bucket, prefix=prefix))
        return sorted(blobs, key=lambda b: b.name)

    def maybe_sample(self, blobs: list[Any]) -> list[Any]:
        """Return either the full list or a uniform random sample of ``sample_size``.

        Sorted output keeps the report ordering deterministic regardless of
        which subset was drawn.
        """
        n = self.config.sample_size
        if n is None or len(blobs) <= n:
            return blobs
        return sorted(self.random.sample(blobs, n), key=lambda b: b.name)

    # ── Cloud lookups ──────────────────────────────────────────────────
    def get_azure_md5(self, blob_name: str) -> str | None:
        """Return the base64 Content-MD5 of an existing Azure blob, or ``None``."""
        blob_client = self.container.get_blob_client(blob_name)
        try:
            props = blob_client.get_blob_properties()
        except ResourceNotFoundError:
            return None
        md5_bytes = props.content_settings.content_md5
        if md5_bytes is None:
            return None
        return base64.b64encode(bytes(md5_bytes)).decode("ascii")

    def get_aws_etag(self, key: str) -> str | None:
        """Return the unquoted ETag of an existing S3 object, or ``None``."""
        try:
            response = self.s3.head_object(Bucket=self.config.aws_bucket, Key=key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey", "NotFound"):
                return None
            raise
        etag: str = response["ETag"]
        return strip_etag_quotes(etag)

    # ── Per-object status determination ───────────────────────────────
    def check_one(self, gcs_blob: Any) -> CheckEntry:
        """Determine the status of one GCS object relative to Azure and AWS."""
        gcs_path: str = gcs_blob.name
        gcs_md5_b64: str | None = gcs_blob.md5_hash
        azure_md5_b64 = self.get_azure_md5(gcs_path)
        aws_etag = self.get_aws_etag(gcs_path)

        status = _determine_status(gcs_md5_b64, azure_md5_b64, aws_etag)

        return CheckEntry(
            gcs_path=gcs_path,
            gcs_md5=gcs_md5_b64,
            azure_md5=azure_md5_b64,
            aws_md5=aws_etag,
            status=status,
        )

    # ── Run orchestration ──────────────────────────────────────────────
    def run(self) -> Report:
        """Run the full three-way verification and return the assembled report."""
        report = Report(
            run_id=str(uuid.uuid4()),
            started_at=_utc_now_iso(),
            gcs_bucket=self.config.gcs_bucket,
            azure_container=self.config.azure_container,
            aws_bucket=self.config.aws_bucket,
            prefix=self.config.prefix,
        )

        all_blobs = self.list_source_objects()
        sampled = self.maybe_sample(all_blobs)
        report.total_objects_checked = len(sampled)
        report.sample_size_used = len(sampled)
        log.info(
            "verify_start",
            total=len(sampled),
            total_in_listing=len(all_blobs),
            prefix=self.config.prefix,
        )

        if not sampled:
            report.completed_at = _utc_now_iso()
            return report

        with ThreadPoolExecutor(max_workers=self.config.parallel) as pool:
            futures = {pool.submit(self.check_one, b): b for b in sampled}
            for future in as_completed(futures):
                entry = future.result()
                _tally(report, entry)

        report.mismatches.sort(key=lambda e: e.gcs_path)
        report.completed_at = _utc_now_iso()
        log.info(
            "verify_done",
            total=report.total_objects_checked,
            matching=report.matching_count,
            mismatch=report.mismatch_count,
            azure_missing=report.missing_in_azure_count,
            aws_missing=report.missing_in_aws_count,
            multipart_unverifiable=report.multipart_unverifiable_count,
        )
        return report

    def write_report(self, report: Report) -> str:
        """Upload the report JSON to ``output_uri``. ``<run_id>`` is substituted."""
        uri = self.config.output_uri.replace("<run_id>", report.run_id)
        bucket_name, object_name = parse_gs_uri(uri)
        payload = json.dumps(report.model_dump(), indent=2, sort_keys=False)
        blob = self.gcs.bucket(bucket_name).blob(object_name)
        blob.upload_from_string(payload, content_type="application/json")
        log.info("report_written", uri=uri)
        return uri


# ──────────────────────────────────────────────────────────────────────────
# Status logic (module-level so tests can exercise it directly)
# ──────────────────────────────────────────────────────────────────────────
def _determine_status(
    gcs_md5_b64: str | None, azure_md5_b64: str | None, aws_etag: str | None
) -> CheckStatus:
    """Decide one object's status from its three observed values.

    Priority (most-actionable first):
      1. Missing on either side wins over mismatches.
      2. A real mismatch wins over multipart-unverifiable.
      3. Multipart-unverifiable applies only when Azure matched and AWS is multipart.
    """
    if azure_md5_b64 is None:
        return "azure_missing"
    if aws_etag is None:
        return "aws_missing"

    azure_match = gcs_md5_b64 is not None and gcs_md5_b64 == azure_md5_b64

    if is_multipart_etag(aws_etag):
        aws_verifiable = False
        aws_match = False  # unknown — placeholder, never read when not verifiable
    else:
        aws_verifiable = True
        if gcs_md5_b64 is None:
            aws_match = False
        else:
            aws_match = aws_etag.lower() == b64_md5_to_hex(gcs_md5_b64).lower()

    if not azure_match:
        return "azure_mismatch"
    if not aws_verifiable:
        return "multipart_unverifiable"
    if not aws_match:
        return "aws_mismatch"
    return "all_match"


def _tally(report: Report, entry: CheckEntry) -> None:
    """Fold a single :class:`CheckEntry` into the report's counters."""
    if entry.status == "all_match":
        report.matching_count += 1
        return
    report.mismatches.append(entry)
    if entry.status in ("azure_mismatch", "aws_mismatch"):
        report.mismatch_count += 1
    elif entry.status == "azure_missing":
        report.missing_in_azure_count += 1
        # The chosen primary status is azure_missing, but if AWS is also gone
        # we count it independently so the operator sees the full picture.
        if entry.aws_md5 is None:
            report.missing_in_aws_count += 1
    elif entry.status == "aws_missing":
        report.missing_in_aws_count += 1
    elif entry.status == "multipart_unverifiable":
        report.multipart_unverifiable_count += 1


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
        prog="verify_checksums",
        description="Three-way cross-cloud checksum parity verifier "
        "(GCS canonical → Azure, AWS).",
    )
    parser.add_argument("--gcs-bucket", required=True, help="GCS source bucket name.")
    parser.add_argument("--azure-account", required=True, help="Azure storage account name.")
    parser.add_argument("--azure-container", required=True, help="Azure blob container name.")
    parser.add_argument("--aws-bucket", required=True, help="AWS S3 bucket name.")
    parser.add_argument("--prefix", default=None, help="Optional GCS prefix narrowing (e.g. raw/).")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="If given, randomly sample this many objects instead of checking all.",
    )
    parser.add_argument(
        "--parallel",
        type=int,
        default=DEFAULT_PARALLEL,
        help=f"Concurrent checks (default: {DEFAULT_PARALLEL}).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output report GCS URI. Default: "
            "gs://<gcs-bucket>/manifests/checksum_verify_<run_id>.json. "
            "The literal '<run_id>' is substituted with the run's UUID."
        ),
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug-level logging.")
    return parser


def print_summary(report: Report) -> None:
    """Print a single-block run summary plus the (truncated) mismatches list."""
    print(f"\n=== checksum verify summary (run_id={report.run_id}) ===")
    print(f"  gcs:   gs://{report.gcs_bucket}/{report.prefix}")
    print(f"  azure: {report.azure_container}")
    print(f"  aws:   s3://{report.aws_bucket}/{report.prefix}")
    print(
        f"  total={report.total_objects_checked} matching={report.matching_count} "
        f"mismatch={report.mismatch_count} "
        f"azure_missing={report.missing_in_azure_count} "
        f"aws_missing={report.missing_in_aws_count} "
        f"multipart_unverifiable={report.multipart_unverifiable_count}"
    )
    if report.mismatches:
        print("  problem entries:")
        for entry in report.mismatches[:20]:
            print(f"    [{entry.status}] {entry.gcs_path}")
        remaining = len(report.mismatches) - 20
        if remaining > 0:
            print(f"    ... and {remaining} more")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    if args.sample_size is not None and args.sample_size < 1:
        print("Config error: --sample-size must be >= 1", file=sys.stderr)
        return 2
    if args.parallel < 1:
        print("Config error: --parallel must be >= 1", file=sys.stderr)
        return 2

    output_uri = args.output or (f"gs://{args.gcs_bucket}/manifests/checksum_verify_<run_id>.json")

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
        aws_creds = fetch_aws_credentials(secret_client, project_id)
    except SecretMissingError as exc:
        log.error("secret_missing", error=str(exc))
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, ValidationError) as exc:
        log.error("secret_invalid", error=str(exc))
        print(f"Error: secret payload invalid: {exc}", file=sys.stderr)
        return 2

    prefix = (args.prefix or "").strip("/")
    if prefix:
        prefix = prefix + "/"

    config = VerifyConfig(
        gcs_bucket=args.gcs_bucket,
        azure_account=args.azure_account,
        azure_container=args.azure_container,
        aws_bucket=args.aws_bucket,
        prefix=prefix,
        sample_size=args.sample_size,
        parallel=args.parallel,
        output_uri=output_uri,
    )

    gcs_client = storage.Client(project=project_id, credentials=credentials)
    azure_client = build_azure_client(azure_creds, args.azure_account)
    s3_client = build_aws_client(aws_creds)

    verifier = Verifier(gcs_client, azure_client, s3_client, config)
    report = verifier.run()
    verifier.write_report(report)
    print_summary(report)

    has_problem = (
        report.mismatch_count > 0
        or report.missing_in_azure_count > 0
        or report.missing_in_aws_count > 0
        or report.multipart_unverifiable_count > 0
    )
    if has_problem:
        print(
            f"\n{len(report.mismatches)} object(s) require attention "
            f"(mismatches, missing, or unverifiable).",
            file=sys.stderr,
        )
        return 1
    return 0


# Public API surface — names callers and tests import from this module.
__all__ = [
    "AwsCredentials",
    "AzureCredentials",
    "CheckEntry",
    "CheckStatus",
    "Report",
    "SecretMissingError",
    "Verifier",
    "VerifyConfig",
    "b64_md5_to_hex",
    "build_aws_client",
    "build_azure_client",
    "fetch_aws_credentials",
    "fetch_azure_credentials",
    "is_multipart_etag",
    "main",
    "parse_gs_uri",
    "strip_etag_quotes",
]


if __name__ == "__main__":
    raise SystemExit(main())
