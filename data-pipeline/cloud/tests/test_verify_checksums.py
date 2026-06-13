"""Tests for ``verify_checksums``.

No cloud service is contacted: small in-memory fakes
(:class:`FakeGcsClient`, :class:`FakeAzureServiceClient`, :class:`FakeS3Client`,
:class:`FakeSecretClient`) stand in for the three cloud SDKs and Secret Manager.
This keeps the suite hermetic, per the data-pipeline rule that tests must not
depend on a live external service.
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
from collections.abc import Iterator
from typing import Any

import pytest
from botocore.exceptions import ClientError
from google.api_core import exceptions as gcp_exceptions
from pydantic import ValidationError

from cloud.verify_checksums import (
    AwsCredentials,
    AzureCredentials,
    CheckEntry,
    Report,
    SecretMissingError,
    Verifier,
    VerifyConfig,
    _determine_status,
    _tally,
    b64_md5_to_hex,
    fetch_aws_credentials,
    fetch_azure_credentials,
    is_multipart_etag,
    main,
    parse_gs_uri,
    strip_etag_quotes,
)


# ──────────────────────────────────────────────────────────────────────────
# Common helpers
# ──────────────────────────────────────────────────────────────────────────
def _b64_md5(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode("ascii")


def _hex_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


# ──────────────────────────────────────────────────────────────────────────
# GCS fake
# ──────────────────────────────────────────────────────────────────────────
class FakeGcsBlob:
    def __init__(self, bucket: FakeGcsBucket, name: str) -> None:
        self._bucket = bucket
        self.name = name

    @property
    def size(self) -> int:
        data = self._bucket.store.get(self.name)
        return len(data) if data is not None else 0

    @property
    def md5_hash(self) -> str | None:
        data = self._bucket.store.get(self.name)
        if data is None:
            return None
        if self.name in self._bucket.suppress_md5_for:
            return None
        return _b64_md5(data)

    def upload_from_string(self, data: str, content_type: str | None = None) -> None:
        self._bucket.store[self.name] = data.encode("utf-8")


class FakeGcsBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self.store: dict[str, bytes] = {}
        self.suppress_md5_for: set[str] = set()

    def blob(self, name: str) -> FakeGcsBlob:
        return FakeGcsBlob(self, name)


class FakeGcsClient:
    def __init__(self) -> None:
        self.buckets: dict[str, FakeGcsBucket] = {}

    def bucket(self, name: str) -> FakeGcsBucket:
        return self.buckets.setdefault(name, FakeGcsBucket(name))

    def list_blobs(self, bucket_name: str, prefix: str | None = None) -> Iterator[FakeGcsBlob]:
        bucket = self.bucket(bucket_name)
        for name in sorted(bucket.store):
            if prefix is None or name.startswith(prefix):
                yield bucket.blob(name)


# ──────────────────────────────────────────────────────────────────────────
# Azure fake
# ──────────────────────────────────────────────────────────────────────────
class _AzureContentSettings:
    def __init__(self, content_md5: bytes | None) -> None:
        self.content_md5 = content_md5


class _AzureBlobProperties:
    def __init__(self, content_md5: bytes | None) -> None:
        self.content_settings = _AzureContentSettings(content_md5)


class _FakeResourceNotFoundError(Exception):
    pass


class FakeAzureBlobClient:
    def __init__(self, container: FakeAzureContainerClient, blob_name: str) -> None:
        self._container = container
        self.blob_name = blob_name

    def get_blob_properties(self) -> _AzureBlobProperties:
        if self.blob_name not in self._container.store:
            raise _FakeResourceNotFoundError("not found")
        return _AzureBlobProperties(self._container.md5s.get(self.blob_name))


class FakeAzureContainerClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.store: dict[str, bytes] = {}
        self.md5s: dict[str, bytes | None] = {}

    def get_blob_client(self, blob_name: str) -> FakeAzureBlobClient:
        return FakeAzureBlobClient(self, blob_name)


class FakeAzureServiceClient:
    def __init__(self) -> None:
        self.containers: dict[str, FakeAzureContainerClient] = {}

    def get_container_client(self, name: str) -> FakeAzureContainerClient:
        return self.containers.setdefault(name, FakeAzureContainerClient(name))


# ──────────────────────────────────────────────────────────────────────────
# AWS fake
# ──────────────────────────────────────────────────────────────────────────
def _make_404_error() -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": "404", "Message": "Not Found"}},
        operation_name="HeadObject",
    )


class FakeS3Client:
    """Stand-in for ``boto3.client('s3')`` — only the methods verify uses."""

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], bytes] = {}
        self.stored_etags: dict[tuple[str, str], str] = {}

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        if (Bucket, Key) not in self.store:
            raise _make_404_error()
        etag = self.stored_etags[(Bucket, Key)]
        return {"ETag": f'"{etag}"', "ContentLength": len(self.store[(Bucket, Key)])}

    # Test convenience — pre-seed an object with content + ETag.
    def put(self, bucket: str, key: str, body: bytes, etag: str | None = None) -> None:
        self.store[(bucket, key)] = body
        self.stored_etags[(bucket, key)] = etag if etag is not None else _hex_md5(body)


# ──────────────────────────────────────────────────────────────────────────
# Secret Manager fake
# ──────────────────────────────────────────────────────────────────────────
class _SecretPayload:
    def __init__(self, data: bytes) -> None:
        self.data = data


class FakeSecretResponse:
    def __init__(self, payload_bytes: bytes) -> None:
        self.payload = _SecretPayload(payload_bytes)


class FakeSecretClient:
    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self.secrets = secrets or {}

    def access_secret_version(self, request: dict[str, str]) -> FakeSecretResponse:
        name = request["name"]
        if name not in self.secrets:
            raise gcp_exceptions.NotFound(f"secret not found: {name}")  # type: ignore[no-untyped-call]
        return FakeSecretResponse(self.secrets[name].encode("utf-8"))


# ──────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _patch_resource_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the SUT catch our fake NotFound when probing Azure blob properties."""
    monkeypatch.setattr("cloud.verify_checksums.ResourceNotFoundError", _FakeResourceNotFoundError)


@pytest.fixture
def three_clouds_in_sync() -> tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client]:
    """GCS, Azure, and AWS all hold the same three objects with matching checksums."""
    gcs = FakeGcsClient()
    azure = FakeAzureServiceClient()
    s3 = FakeS3Client()

    bucket = gcs.bucket("maisys-data-dev")
    container = azure.get_container_client("maisys-data-stage")
    for name, data in [
        ("raw/a.pdf", b"alpha"),
        ("raw/b.pdf", b"bravo"),
        ("raw/sub/c.pdf", b"charlie"),
    ]:
        bucket.store[name] = data
        container.store[name] = data
        container.md5s[name] = hashlib.md5(data).digest()
        s3.put("maisys-data-prod", name, data)
    return gcs, azure, s3


def make_config(**overrides: Any) -> VerifyConfig:
    defaults: dict[str, Any] = {
        "gcs_bucket": "maisys-data-dev",
        "azure_account": "maisysstage",
        "azure_container": "maisys-data-stage",
        "aws_bucket": "maisys-data-prod",
        "prefix": "raw/",
        "parallel": 2,
        "output_uri": "gs://maisys-data-dev/manifests/checksum_verify_<run_id>.json",
    }
    defaults.update(overrides)
    return VerifyConfig(**defaults)


# ──────────────────────────────────────────────────────────────────────────
# Pure helpers
# ──────────────────────────────────────────────────────────────────────────
def test_parse_gs_uri_variants() -> None:
    assert parse_gs_uri("gs://bucket/path/to/obj") == ("bucket", "path/to/obj")
    with pytest.raises(ValueError):
        parse_gs_uri("s3://bucket/obj")
    with pytest.raises(ValueError):
        parse_gs_uri("gs://bucket-only")  # no object portion


def test_strip_etag_quotes() -> None:
    assert strip_etag_quotes('"abc"') == "abc"
    assert strip_etag_quotes("abc") == "abc"


def test_is_multipart_etag() -> None:
    assert is_multipart_etag("deadbeef-3")
    assert not is_multipart_etag("deadbeef")


def test_b64_md5_to_hex_roundtrip() -> None:
    data = b"hello world"
    b64 = base64.b64encode(hashlib.md5(data).digest()).decode("ascii")
    assert b64_md5_to_hex(b64) == hashlib.md5(data).hexdigest()


# ──────────────────────────────────────────────────────────────────────────
# Config models
# ──────────────────────────────────────────────────────────────────────────
def test_verify_config_rejects_zero_parallel() -> None:
    with pytest.raises(ValidationError):
        make_config(parallel=0)


def test_verify_config_rejects_zero_sample_size() -> None:
    with pytest.raises(ValidationError):
        make_config(sample_size=0)


def test_azure_credentials_accept_camelcase() -> None:
    creds = AzureCredentials.model_validate(
        {
            "tenantId": "t",
            "clientId": "c",
            "clientSecret": "s",
            "subscriptionId": "sub",
            "storageAccount": "acct",
        }
    )
    assert creds.tenant_id == "t"


def test_aws_credentials_accept_camelcase() -> None:
    creds = AwsCredentials.model_validate(
        {
            "accessKeyId": "k",
            "secretAccessKey": "s",
            "region": "us-east-1",
            "bucket": "b",
        }
    )
    assert creds.access_key_id == "k"


# ──────────────────────────────────────────────────────────────────────────
# Secret Manager integration
# ──────────────────────────────────────────────────────────────────────────
def _azure_secret_payload() -> str:
    return json.dumps(
        {
            "tenantId": "t-uuid",
            "clientId": "c-uuid",
            "clientSecret": "shhh",
            "subscriptionId": "s-uuid",
            "storageAccount": "maisysstage",
        }
    )


def _aws_secret_payload() -> str:
    return json.dumps(
        {
            "accessKeyId": "AKIA0000",
            "secretAccessKey": "shhh-very-secret",
            "region": "us-east-1",
            "bucket": "maisys-data-prod",
        }
    )


def test_fetch_azure_credentials_missing_raises_with_remediation() -> None:
    client = FakeSecretClient(secrets={})
    with pytest.raises(SecretMissingError) as exc_info:
        fetch_azure_credentials(client, "maisys-dev")
    msg = str(exc_info.value)
    assert "azure-service-principal" in msg
    assert "gcloud secrets create azure-service-principal" in msg
    assert "--project=maisys-dev" in msg


def test_fetch_aws_credentials_missing_raises_with_remediation() -> None:
    client = FakeSecretClient(secrets={})
    with pytest.raises(SecretMissingError) as exc_info:
        fetch_aws_credentials(client, "maisys-dev")
    msg = str(exc_info.value)
    assert "aws-credentials" in msg
    assert "gcloud secrets create aws-credentials" in msg
    assert "--project=maisys-dev" in msg


def test_fetch_azure_credentials_happy_path() -> None:
    secret_key = "projects/maisys-dev/secrets/azure-service-principal/versions/latest"
    client = FakeSecretClient(secrets={secret_key: _azure_secret_payload()})
    creds = fetch_azure_credentials(client, "maisys-dev")
    assert creds.tenant_id == "t-uuid"


def test_fetch_aws_credentials_happy_path() -> None:
    secret_key = "projects/maisys-dev/secrets/aws-credentials/versions/latest"
    client = FakeSecretClient(secrets={secret_key: _aws_secret_payload()})
    creds = fetch_aws_credentials(client, "maisys-dev")
    assert creds.region == "us-east-1"


# ──────────────────────────────────────────────────────────────────────────
# Status logic (module-level pure function)
# ──────────────────────────────────────────────────────────────────────────
def test_determine_status_all_match() -> None:
    gcs = _b64_md5(b"alpha")
    azure = _b64_md5(b"alpha")
    aws = _hex_md5(b"alpha")
    assert _determine_status(gcs, azure, aws) == "all_match"


def test_determine_status_azure_missing_wins_over_aws_missing() -> None:
    gcs = _b64_md5(b"alpha")
    assert _determine_status(gcs, None, None) == "azure_missing"


def test_determine_status_aws_missing() -> None:
    gcs = _b64_md5(b"alpha")
    azure = _b64_md5(b"alpha")
    assert _determine_status(gcs, azure, None) == "aws_missing"


def test_determine_status_azure_mismatch() -> None:
    gcs = _b64_md5(b"alpha")
    azure = _b64_md5(b"DIFFERENT")
    aws = _hex_md5(b"alpha")
    assert _determine_status(gcs, azure, aws) == "azure_mismatch"


def test_determine_status_aws_mismatch_single_part() -> None:
    gcs = _b64_md5(b"alpha")
    azure = _b64_md5(b"alpha")
    aws = _hex_md5(b"DIFFERENT")
    assert _determine_status(gcs, azure, aws) == "aws_mismatch"


def test_determine_status_multipart_unverifiable_when_azure_matches() -> None:
    gcs = _b64_md5(b"alpha")
    azure = _b64_md5(b"alpha")
    aws = "deadbeefdeadbeefdeadbeefdeadbeef-5"  # multipart ETag
    assert _determine_status(gcs, azure, aws) == "multipart_unverifiable"


def test_determine_status_azure_mismatch_wins_over_multipart_unverifiable() -> None:
    gcs = _b64_md5(b"alpha")
    azure = _b64_md5(b"DIFFERENT")
    aws = "deadbeefdeadbeefdeadbeefdeadbeef-5"
    assert _determine_status(gcs, azure, aws) == "azure_mismatch"


# ──────────────────────────────────────────────────────────────────────────
# End-to-end runs (Verifier)
# ──────────────────────────────────────────────────────────────────────────
def test_full_run_all_match(
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    config = make_config()
    verifier = Verifier(gcs, azure, s3, config)

    report = verifier.run()
    assert report.total_objects_checked == 3
    assert report.matching_count == 3
    assert report.mismatch_count == 0
    assert report.missing_in_azure_count == 0
    assert report.missing_in_aws_count == 0
    assert report.multipart_unverifiable_count == 0
    assert report.mismatches == []


def test_single_azure_mismatch_detected(
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    # Corrupt one Azure blob — different content + different MD5.
    container = azure.get_container_client("maisys-data-stage")
    container.store["raw/a.pdf"] = b"DIFFERENT"
    container.md5s["raw/a.pdf"] = hashlib.md5(b"DIFFERENT").digest()

    config = make_config()
    verifier = Verifier(gcs, azure, s3, config)
    report = verifier.run()

    assert report.matching_count == 2
    assert report.mismatch_count == 1
    assert len(report.mismatches) == 1
    entry = report.mismatches[0]
    assert entry.gcs_path == "raw/a.pdf"
    assert entry.status == "azure_mismatch"


def test_single_aws_mismatch_detected(
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    s3.put("maisys-data-prod", "raw/a.pdf", b"DIFFERENT")  # overwrite + new etag

    config = make_config()
    verifier = Verifier(gcs, azure, s3, config)
    report = verifier.run()

    assert report.mismatch_count == 1
    assert report.mismatches[0].status == "aws_mismatch"


def test_missing_in_one_cloud_aws(
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    s3.store.pop(("maisys-data-prod", "raw/a.pdf"))
    s3.stored_etags.pop(("maisys-data-prod", "raw/a.pdf"))

    config = make_config()
    verifier = Verifier(gcs, azure, s3, config)
    report = verifier.run()

    assert report.missing_in_aws_count == 1
    assert report.missing_in_azure_count == 0
    assert len(report.mismatches) == 1
    assert report.mismatches[0].status == "aws_missing"


def test_missing_in_one_cloud_azure(
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    container = azure.get_container_client("maisys-data-stage")
    container.store.pop("raw/a.pdf")
    container.md5s.pop("raw/a.pdf")

    config = make_config()
    verifier = Verifier(gcs, azure, s3, config)
    report = verifier.run()

    assert report.missing_in_azure_count == 1
    assert report.missing_in_aws_count == 0
    assert report.mismatches[0].status == "azure_missing"


def test_missing_in_two_clouds_counts_both_independently(
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    """An object missing in BOTH Azure and AWS increments both missing counters."""
    gcs, azure, s3 = three_clouds_in_sync
    container = azure.get_container_client("maisys-data-stage")
    container.store.pop("raw/a.pdf")
    container.md5s.pop("raw/a.pdf")
    s3.store.pop(("maisys-data-prod", "raw/a.pdf"))
    s3.stored_etags.pop(("maisys-data-prod", "raw/a.pdf"))

    config = make_config()
    verifier = Verifier(gcs, azure, s3, config)
    report = verifier.run()

    # Primary status is azure_missing (priority), but BOTH counters tick up.
    assert report.missing_in_azure_count == 1
    assert report.missing_in_aws_count == 1
    assert len(report.mismatches) == 1
    entry = report.mismatches[0]
    assert entry.status == "azure_missing"
    assert entry.azure_md5 is None
    assert entry.aws_md5 is None


def test_multipart_aws_etag_marked_unverifiable(
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    """An existing S3 object with a multipart ETag is reported as unverifiable."""
    gcs, azure, s3 = three_clouds_in_sync
    # Replace raw/a.pdf's stored ETag with a multipart one. Azure still matches.
    s3.stored_etags[("maisys-data-prod", "raw/a.pdf")] = "deadbeefdeadbeefdeadbeefdeadbeef-3"

    config = make_config()
    verifier = Verifier(gcs, azure, s3, config)
    report = verifier.run()

    assert report.multipart_unverifiable_count == 1
    assert report.matching_count == 2
    assert report.mismatch_count == 0
    assert report.missing_in_aws_count == 0
    entry = report.mismatches[0]
    assert entry.status == "multipart_unverifiable"
    assert entry.aws_md5 == "deadbeefdeadbeefdeadbeefdeadbeef-3"


def test_sample_size_narrows_listing(
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    config = make_config(sample_size=2)
    verifier = Verifier(gcs, azure, s3, config, random_instance=random.Random(42))
    report = verifier.run()

    assert report.total_objects_checked == 2
    assert report.sample_size_used == 2


def test_sample_size_above_total_checks_all(
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    config = make_config(sample_size=999)
    verifier = Verifier(gcs, azure, s3, config)
    report = verifier.run()

    assert report.total_objects_checked == 3


def test_prefix_narrowing_filters_listing(
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    config = make_config(prefix="raw/sub/")
    verifier = Verifier(gcs, azure, s3, config)
    report = verifier.run()

    assert report.total_objects_checked == 1
    assert report.matching_count == 1


def test_empty_listing_returns_empty_report() -> None:
    gcs = FakeGcsClient()
    azure = FakeAzureServiceClient()
    s3 = FakeS3Client()
    gcs.bucket("maisys-data-dev")  # exists but empty

    config = make_config()
    verifier = Verifier(gcs, azure, s3, config)
    report = verifier.run()

    assert report.total_objects_checked == 0
    assert report.matching_count == 0
    assert report.mismatches == []


# ──────────────────────────────────────────────────────────────────────────
# Report writing
# ──────────────────────────────────────────────────────────────────────────
def test_write_report_substitutes_run_id(
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    config = make_config()
    verifier = Verifier(gcs, azure, s3, config)
    report = verifier.run()
    uri = verifier.write_report(report)

    assert "<run_id>" not in uri
    assert report.run_id in uri
    bucket_store = gcs.bucket("maisys-data-dev").store
    object_name = f"manifests/checksum_verify_{report.run_id}.json"
    assert object_name in bucket_store
    written = json.loads(bucket_store[object_name].decode("utf-8"))
    assert written["run_id"] == report.run_id
    assert written["total_objects_checked"] == 3


# ──────────────────────────────────────────────────────────────────────────
# Tally function (regression-style coverage)
# ──────────────────────────────────────────────────────────────────────────
def test_tally_does_not_add_match_to_mismatches() -> None:
    report = Report(
        run_id="r",
        started_at="t",
        gcs_bucket="g",
        azure_container="c",
        aws_bucket="b",
        prefix="",
    )
    _tally(
        report,
        CheckEntry(
            gcs_path="x",
            gcs_md5="m",
            azure_md5="m",
            aws_md5="m",
            status="all_match",
        ),
    )
    assert report.matching_count == 1
    assert report.mismatches == []


def test_tally_independent_missing_counters_for_both_missing() -> None:
    report = Report(
        run_id="r",
        started_at="t",
        gcs_bucket="g",
        azure_container="c",
        aws_bucket="b",
        prefix="",
    )
    _tally(
        report,
        CheckEntry(
            gcs_path="x",
            gcs_md5="m",
            azure_md5=None,
            aws_md5=None,
            status="azure_missing",
        ),
    )
    assert report.missing_in_azure_count == 1
    assert report.missing_in_aws_count == 1


# ──────────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ──────────────────────────────────────────────────────────────────────────
def _install_main_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gcs: FakeGcsClient,
    azure: FakeAzureServiceClient,
    s3: FakeS3Client,
    have_azure_secret: bool = True,
    have_aws_secret: bool = True,
) -> None:
    monkeypatch.setattr(
        "cloud.verify_checksums.get_application_default_credentials",
        lambda *a, **k: (object(), "maisys-dev"),
    )
    secrets: dict[str, str] = {}
    if have_azure_secret:
        secrets["projects/maisys-dev/secrets/azure-service-principal/versions/latest"] = (
            _azure_secret_payload()
        )
    if have_aws_secret:
        secrets["projects/maisys-dev/secrets/aws-credentials/versions/latest"] = (
            _aws_secret_payload()
        )
    fake_secret = FakeSecretClient(secrets=secrets)
    monkeypatch.setattr(
        "cloud.verify_checksums.secretmanager.SecretManagerServiceClient",
        lambda *a, **k: fake_secret,
    )
    monkeypatch.setattr("cloud.verify_checksums.storage.Client", lambda *a, **k: gcs)
    monkeypatch.setattr("cloud.verify_checksums.build_azure_client", lambda *a, **k: azure)
    monkeypatch.setattr("cloud.verify_checksums.build_aws_client", lambda *a, **k: s3)


def _cli_args() -> list[str]:
    return [
        "--gcs-bucket",
        "maisys-data-dev",
        "--azure-account",
        "maisysstage",
        "--azure-container",
        "maisys-data-stage",
        "--aws-bucket",
        "maisys-data-prod",
        "--prefix",
        "raw/",
        "--parallel",
        "2",
    ]


def test_main_all_match_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    _install_main_fakes(monkeypatch, gcs=gcs, azure=azure, s3=s3)
    rc = main(_cli_args())
    assert rc == 0


def test_main_mismatch_returns_one(
    monkeypatch: pytest.MonkeyPatch,
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    s3.put("maisys-data-prod", "raw/a.pdf", b"DIFFERENT")  # introduce mismatch
    _install_main_fakes(monkeypatch, gcs=gcs, azure=azure, s3=s3)
    rc = main(_cli_args())
    assert rc == 1


def test_main_multipart_unverifiable_returns_one(
    monkeypatch: pytest.MonkeyPatch,
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    s3.stored_etags[("maisys-data-prod", "raw/a.pdf")] = "deadbeef-5"
    _install_main_fakes(monkeypatch, gcs=gcs, azure=azure, s3=s3)
    rc = main(_cli_args())
    # Unverifiable counts as "requires attention" per the spec's exit semantics.
    assert rc == 1


def test_main_missing_azure_secret_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    _install_main_fakes(monkeypatch, gcs=gcs, azure=azure, s3=s3, have_azure_secret=False)
    rc = main(_cli_args())
    assert rc == 2


def test_main_missing_aws_secret_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    _install_main_fakes(monkeypatch, gcs=gcs, azure=azure, s3=s3, have_aws_secret=False)
    rc = main(_cli_args())
    assert rc == 2


def test_main_writes_report_to_default_output(
    monkeypatch: pytest.MonkeyPatch,
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    _install_main_fakes(monkeypatch, gcs=gcs, azure=azure, s3=s3)
    rc = main(_cli_args())
    assert rc == 0
    bucket_store = gcs.bucket("maisys-data-dev").store
    assert any(k.startswith("manifests/checksum_verify_") for k in bucket_store)


def test_main_bad_sample_size_returns_two(
    monkeypatch: pytest.MonkeyPatch,
    three_clouds_in_sync: tuple[FakeGcsClient, FakeAzureServiceClient, FakeS3Client],
) -> None:
    gcs, azure, s3 = three_clouds_in_sync
    _install_main_fakes(monkeypatch, gcs=gcs, azure=azure, s3=s3)
    rc = main([*_cli_args(), "--sample-size", "0"])
    assert rc == 2
