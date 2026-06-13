"""Tests for ``sync_gcs_to_aws``.

Neither GCS nor S3 is contacted: small in-memory fakes
(:class:`FakeGcsClient`, :class:`FakeS3Client`, :class:`FakeSecretClient`)
stand in for the real cloud SDKs. This keeps the suite hermetic, per the
data-pipeline rule that tests must not depend on a live external service.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterator
from typing import Any

import pytest
from botocore.exceptions import ClientError
from google.api_core import exceptions as gcp_exceptions
from pydantic import ValidationError

from cloud.sync_gcs_to_aws import (
    AwsCredentials,
    AwsSecretMissingError,
    EtagMismatchError,
    SyncConfig,
    Syncer,
    compute_multipart_etag,
    fetch_aws_credentials,
    is_multipart_etag,
    join_prefix,
    main,
    parse_gs_uri,
    s3_object_url,
    strip_etag_quotes,
)


# ──────────────────────────────────────────────────────────────────────────
# In-memory fakes
# ──────────────────────────────────────────────────────────────────────────
def _b64_md5(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode("ascii")


def _hex_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class FakeGcsBlob:
    """Stand-in for ``google.cloud.storage.Blob``."""

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

    def download_as_bytes(self, start: int | None = None, end: int | None = None) -> bytes:
        data = self._bucket.store.get(self.name)
        if data is None:
            raise KeyError(self.name)
        if start is None and end is None:
            return data
        s = start or 0
        # ``end`` follows the google-cloud-storage convention: inclusive.
        e = (end + 1) if end is not None else len(data)
        return data[s:e]

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
    """Stand-in for ``google.cloud.storage.Client``."""

    def __init__(self) -> None:
        self.buckets: dict[str, FakeGcsBucket] = {}

    def bucket(self, name: str) -> FakeGcsBucket:
        return self.buckets.setdefault(name, FakeGcsBucket(name))

    def list_blobs(self, bucket_name: str, prefix: str | None = None) -> Iterator[FakeGcsBlob]:
        bucket = self.bucket(bucket_name)
        for name in sorted(bucket.store):
            if prefix is None or name.startswith(prefix):
                yield bucket.blob(name)


def _make_404_error() -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": "404", "Message": "Not Found"}},
        operation_name="HeadObject",
    )


class FakeS3Client:
    """Stand-in for ``boto3.client('s3')``.

    Stores object bytes and a stored ETag (which is what ``head_object`` returns
    on subsequent calls — so corruption simulations can lie about the body but
    have the stored ETag still reflect what's actually on disk, just like real
    S3 does after an integrity check would fail).
    """

    def __init__(self) -> None:
        self.store: dict[tuple[str, str], bytes] = {}
        self.stored_etags: dict[tuple[str, str], str] = {}
        # Multipart upload bookkeeping
        self._multiparts: dict[str, dict[int, bytes]] = {}
        self._multipart_key: dict[str, tuple[str, str]] = {}
        # Failure injection
        self.fail_uploads_for: set[str] = set()
        self.corrupt_uploads_for: dict[str, int] = {}
        self.attempts: dict[str, int] = {}
        self.aborted_uploads: list[str] = []

    # ── Single-part API ────────────────────────────────────────────────
    def put_object(
        self, Bucket: str, Key: str, Body: bytes, ContentMD5: str | None = None
    ) -> dict[str, Any]:
        if Key in self.fail_uploads_for:
            self.attempts[Key] = self.attempts.get(Key, 0) + 1
            raise RuntimeError(f"injected put_object failure for {Key}")
        if self.corrupt_uploads_for.get(Key, 0) > 0:
            self.corrupt_uploads_for[Key] -= 1
            stored = b"corrupted-bytes"
        else:
            stored = Body
        self.store[(Bucket, Key)] = stored
        # Real S3 stores ETag = hex MD5 of the actual stored bytes.
        etag = _hex_md5(stored)
        self.stored_etags[(Bucket, Key)] = etag
        return {"ETag": f'"{etag}"'}

    def head_object(self, Bucket: str, Key: str) -> dict[str, Any]:
        if (Bucket, Key) not in self.store:
            raise _make_404_error()
        etag = self.stored_etags[(Bucket, Key)]
        return {"ETag": f'"{etag}"', "ContentLength": len(self.store[(Bucket, Key)])}

    # ── Multipart API ──────────────────────────────────────────────────
    def create_multipart_upload(self, Bucket: str, Key: str) -> dict[str, Any]:
        upload_id = f"upload-{len(self._multiparts) + 1}"
        self._multiparts[upload_id] = {}
        self._multipart_key[upload_id] = (Bucket, Key)
        return {"UploadId": upload_id}

    def upload_part(
        self,
        Bucket: str,
        Key: str,
        PartNumber: int,
        UploadId: str,
        Body: bytes,
        ContentMD5: str | None = None,
    ) -> dict[str, Any]:
        if Key in self.fail_uploads_for:
            self.attempts[Key] = self.attempts.get(Key, 0) + 1
            raise RuntimeError(f"injected upload_part failure for {Key}")
        self._multiparts[UploadId][PartNumber] = Body
        part_etag = _hex_md5(Body)
        return {"ETag": f'"{part_etag}"'}

    def complete_multipart_upload(
        self,
        Bucket: str,
        Key: str,
        UploadId: str,
        MultipartUpload: dict[str, Any],
    ) -> dict[str, Any]:
        parts = self._multiparts.pop(UploadId, {})
        self._multipart_key.pop(UploadId, None)
        ordered_part_bytes = [parts[i] for i in sorted(parts)]
        if self.corrupt_uploads_for.get(Key, 0) > 0:
            self.corrupt_uploads_for[Key] -= 1
            # Simulate corruption: discard parts, replace with a single corrupt
            # blob. The resulting ETag is a no-dash hex MD5 of garbage, which
            # the SUT will compare against its expected ``<hex>-<N>`` and fail.
            stored = b"corrupted-multipart-bytes"
            self.store[(Bucket, Key)] = stored
            etag = _hex_md5(stored)
            self.stored_etags[(Bucket, Key)] = etag
            return {"ETag": f'"{etag}"'}
        full_bytes = b"".join(ordered_part_bytes)
        self.store[(Bucket, Key)] = full_bytes
        # Real multipart ETag: hex(md5(concat(part_md5s))) + "-" + str(num_parts).
        part_md5s = [hashlib.md5(p).digest() for p in ordered_part_bytes]
        etag = f"{hashlib.md5(b''.join(part_md5s)).hexdigest()}-{len(part_md5s)}"
        self.stored_etags[(Bucket, Key)] = etag
        return {"ETag": f'"{etag}"'}

    def abort_multipart_upload(self, Bucket: str, Key: str, UploadId: str) -> dict[str, Any]:
        self._multiparts.pop(UploadId, None)
        self._multipart_key.pop(UploadId, None)
        self.aborted_uploads.append(UploadId)
        return {}


class FakeSecretResponse:
    def __init__(self, payload_bytes: bytes) -> None:
        self.payload = _SecretPayload(payload_bytes)


class _SecretPayload:
    def __init__(self, data: bytes) -> None:
        self.data = data


class FakeSecretClient:
    """Stand-in for ``google.cloud.secretmanager.SecretManagerServiceClient``."""

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
@pytest.fixture
def gcs_with_objects() -> FakeGcsClient:
    client = FakeGcsClient()
    bucket = client.bucket("maisys-data-dev")
    bucket.store["raw/a.pdf"] = b"alpha"
    bucket.store["raw/b.pdf"] = b"bravo"
    bucket.store["raw/sub/c.pdf"] = b"charlie"
    bucket.store["beta_training/x.jsonl"] = b'{"k":"v"}'
    return client


def make_config(**overrides: Any) -> SyncConfig:
    defaults: dict[str, Any] = {
        "source_bucket": "maisys-data-dev",
        "source_prefix": "",
        "target_bucket": "maisys-data-prod",
        "parallel": 2,
        "retry_attempts": 3,
        "block_size_bytes": 4,  # tiny on purpose so chunked path is reachable
        "chunked_threshold_bytes": 10,  # any file > 10 bytes uses chunked path
        "manifest_bucket": "maisys-data-dev",
    }
    defaults.update(overrides)
    return SyncConfig(**defaults)


# ──────────────────────────────────────────────────────────────────────────
# Pure helpers
# ──────────────────────────────────────────────────────────────────────────
def test_parse_gs_uri_variants() -> None:
    assert parse_gs_uri("gs://bucket") == ("bucket", "")
    assert parse_gs_uri("gs://bucket/") == ("bucket", "")
    assert parse_gs_uri("gs://bucket/path/to/obj") == ("bucket", "path/to/obj")
    with pytest.raises(ValueError):
        parse_gs_uri("s3://bucket")
    with pytest.raises(ValueError):
        parse_gs_uri("gs:///no-bucket")


def test_join_prefix_combinations() -> None:
    assert join_prefix("", None) == ""
    assert join_prefix("", "raw/") == "raw/"
    assert join_prefix("raw/", None) == "raw/"
    assert join_prefix("raw", "more") == "raw/more/"
    assert join_prefix("raw/", "/more/") == "raw/more/"
    assert join_prefix("a/b", "c/d") == "a/b/c/d/"
    assert join_prefix("/", None) == ""


def test_s3_object_url() -> None:
    assert s3_object_url("bkt", "raw/a.pdf") == "s3://bkt/raw/a.pdf"


def test_strip_etag_quotes() -> None:
    assert strip_etag_quotes('"abc123"') == "abc123"
    assert strip_etag_quotes("abc123") == "abc123"
    assert strip_etag_quotes('"abc-5"') == "abc-5"


def test_is_multipart_etag() -> None:
    assert is_multipart_etag("abc123-5")
    assert not is_multipart_etag("abc123")


def test_compute_multipart_etag_against_known_value() -> None:
    # Sanity-check the algorithm against a hand-computed value.
    p1 = b"AAAA"
    p2 = b"BBBB"
    digests = [hashlib.md5(p1).digest(), hashlib.md5(p2).digest()]
    expected_hex = hashlib.md5(b"".join(digests)).hexdigest()
    expected = f"{expected_hex}-2"
    assert compute_multipart_etag(digests, 2) == expected


# ──────────────────────────────────────────────────────────────────────────
# Config model
# ──────────────────────────────────────────────────────────────────────────
def test_sync_config_rejects_zero_parallel() -> None:
    with pytest.raises(ValidationError):
        make_config(parallel=0)


def test_sync_config_rejects_zero_retry_attempts() -> None:
    with pytest.raises(ValidationError):
        make_config(retry_attempts=0)


def test_aws_credentials_accept_camelcase() -> None:
    creds = AwsCredentials.model_validate(
        {
            "accessKeyId": "AKIA...",
            "secretAccessKey": "shhh",
            "region": "us-east-1",
            "bucket": "maisys-data-prod",
        }
    )
    assert creds.access_key_id == "AKIA..."
    assert creds.region == "us-east-1"


def test_aws_credentials_reject_missing_keys() -> None:
    with pytest.raises(ValidationError):
        AwsCredentials.model_validate({"accessKeyId": "k"})


# ──────────────────────────────────────────────────────────────────────────
# Secret Manager integration
# ──────────────────────────────────────────────────────────────────────────
def _secret_payload() -> str:
    return json.dumps(
        {
            "accessKeyId": "AKIA0000000000000000",
            "secretAccessKey": "shhh-very-secret",
            "region": "us-east-1",
            "bucket": "maisys-data-prod",
        }
    )


def test_fetch_aws_credentials_happy_path() -> None:
    secret_key = "projects/maisys-dev/secrets/aws-credentials/versions/latest"
    client = FakeSecretClient(secrets={secret_key: _secret_payload()})
    creds = fetch_aws_credentials(client, "maisys-dev")
    assert creds.access_key_id == "AKIA0000000000000000"


def test_fetch_aws_credentials_missing_raises_with_remediation() -> None:
    client = FakeSecretClient(secrets={})
    with pytest.raises(AwsSecretMissingError) as exc_info:
        fetch_aws_credentials(client, "maisys-dev")
    msg = str(exc_info.value)
    assert "aws-credentials" in msg
    assert "maisys-dev" in msg
    assert "gcloud secrets create aws-credentials" in msg
    assert "gcloud secrets versions add aws-credentials" in msg
    assert "--project=maisys-dev" in msg


def test_fetch_aws_credentials_invalid_json_raises() -> None:
    client = FakeSecretClient(
        secrets={"projects/p/secrets/aws-credentials/versions/latest": "{not json"}
    )
    with pytest.raises(ValueError):
        fetch_aws_credentials(client, "p")


def test_fetch_aws_credentials_missing_keys_raises() -> None:
    client = FakeSecretClient(
        secrets={
            "projects/p/secrets/aws-credentials/versions/latest": json.dumps({"accessKeyId": "k"})
        }
    )
    with pytest.raises(ValidationError):
        fetch_aws_credentials(client, "p")


# ──────────────────────────────────────────────────────────────────────────
# Skip / force / dry-run
# ──────────────────────────────────────────────────────────────────────────
def test_full_run_syncs_all_and_writes_manifest(gcs_with_objects: FakeGcsClient) -> None:
    s3 = FakeS3Client()
    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, s3, config, sleep=lambda _: None)

    manifest = syncer.run()
    assert manifest.total_files == 3
    assert manifest.synced_count == 3
    assert manifest.failed_count == 0
    assert manifest.skipped_count == 0

    assert s3.store[("maisys-data-prod", "raw/a.pdf")] == b"alpha"
    assert s3.store[("maisys-data-prod", "raw/sub/c.pdf")] == b"charlie"
    assert ("maisys-data-prod", "beta_training/x.jsonl") not in s3.store

    uri = syncer.write_manifest(manifest)
    assert uri.startswith("gs://maisys-data-dev/manifests/sync_to_aws_")
    bucket_store = gcs_with_objects.bucket("maisys-data-dev").store
    manifest_object = f"manifests/sync_to_aws_{manifest.run_id}.json"
    written = json.loads(bucket_store[manifest_object].decode("utf-8"))
    assert written["run_id"] == manifest.run_id
    assert written["synced_count"] == 3
    assert written["failed_count"] == 0


def test_skip_if_etag_matches_single_part(gcs_with_objects: FakeGcsClient) -> None:
    s3 = FakeS3Client()
    # Pre-seed S3 with matching content + correct hex ETag → should be skipped.
    s3.store[("maisys-data-prod", "raw/a.pdf")] = b"alpha"
    s3.stored_etags[("maisys-data-prod", "raw/a.pdf")] = _hex_md5(b"alpha")

    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, s3, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.skipped_count == 1
    assert manifest.synced_count == 2
    assert manifest.failed_count == 0


def test_multipart_etag_is_conservatively_reuploaded(gcs_with_objects: FakeGcsClient) -> None:
    """An existing object with a multipart ETag should be re-uploaded, not skipped."""
    s3 = FakeS3Client()
    # Forge an existing dash-style ETag — the SUT cannot verify content match
    # without re-downloading the source, so it must NOT skip.
    s3.store[("maisys-data-prod", "raw/a.pdf")] = b"alpha"
    s3.stored_etags[("maisys-data-prod", "raw/a.pdf")] = "deadbeef-3"

    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, s3, config, sleep=lambda _: None)
    manifest = syncer.run()

    # All three files re-uploaded; raw/a.pdf is overwritten with correct bytes.
    assert manifest.synced_count == 3
    assert manifest.skipped_count == 0
    assert s3.store[("maisys-data-prod", "raw/a.pdf")] == b"alpha"
    # And its ETag is now a plain hex MD5 (single-part).
    assert "-" not in s3.stored_etags[("maisys-data-prod", "raw/a.pdf")]


def test_stale_etag_is_not_skipped(gcs_with_objects: FakeGcsClient) -> None:
    s3 = FakeS3Client()
    s3.store[("maisys-data-prod", "raw/a.pdf")] = b"STALE"
    s3.stored_etags[("maisys-data-prod", "raw/a.pdf")] = _hex_md5(b"STALE")

    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, s3, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.synced_count == 3
    assert manifest.skipped_count == 0
    assert s3.store[("maisys-data-prod", "raw/a.pdf")] == b"alpha"


def test_force_reuploads_even_when_etag_matches(gcs_with_objects: FakeGcsClient) -> None:
    s3 = FakeS3Client()
    s3.store[("maisys-data-prod", "raw/a.pdf")] = b"alpha"
    s3.stored_etags[("maisys-data-prod", "raw/a.pdf")] = _hex_md5(b"alpha")

    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, s3, config, force=True, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.skipped_count == 0
    assert manifest.synced_count == 3


def test_dry_run_does_not_upload(gcs_with_objects: FakeGcsClient) -> None:
    s3 = FakeS3Client()
    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, s3, config, dry_run=True, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.synced_count == 3
    assert s3.store == {}


def test_prefix_narrowing(gcs_with_objects: FakeGcsClient) -> None:
    s3 = FakeS3Client()
    config = make_config(source_prefix="raw/sub/")
    syncer = Syncer(gcs_with_objects, s3, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.total_files == 1
    assert manifest.synced_count == 1
    assert list(s3.store) == [("maisys-data-prod", "raw/sub/c.pdf")]


# ──────────────────────────────────────────────────────────────────────────
# Retry behaviour
# ──────────────────────────────────────────────────────────────────────────
def test_etag_mismatch_retried_then_succeeds(gcs_with_objects: FakeGcsClient) -> None:
    s3 = FakeS3Client()
    # First put_object lands "corrupted" → stored ETag won't match source MD5.
    s3.corrupt_uploads_for["raw/a.pdf"] = 1

    config = make_config(source_prefix="raw/", retry_attempts=3)
    syncer = Syncer(gcs_with_objects, s3, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.failed_count == 0
    assert manifest.synced_count == 3
    entry = next(f for f in manifest.files if f.object_name == "raw/a.pdf")
    assert entry.status == "synced"
    assert entry.attempts == 2
    assert s3.store[("maisys-data-prod", "raw/a.pdf")] == b"alpha"


def test_etag_mismatch_exhausts_retries_and_fails(gcs_with_objects: FakeGcsClient) -> None:
    s3 = FakeS3Client()
    s3.corrupt_uploads_for["raw/a.pdf"] = 99  # corrupt every attempt

    config = make_config(source_prefix="raw/", retry_attempts=3)
    syncer = Syncer(gcs_with_objects, s3, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.failed_count == 1
    entry = next(f for f in manifest.files if f.object_name == "raw/a.pdf")
    assert entry.status == "failed"
    assert entry.attempts == 3
    assert entry.error is not None


def test_partial_failure_run(gcs_with_objects: FakeGcsClient) -> None:
    s3 = FakeS3Client()
    s3.fail_uploads_for.add("raw/a.pdf")

    config = make_config(source_prefix="raw/", retry_attempts=2)
    syncer = Syncer(gcs_with_objects, s3, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.synced_count == 2
    assert manifest.failed_count == 1
    assert manifest.failed_files == ["raw/a.pdf"]


def test_source_md5_missing_is_failure(gcs_with_objects: FakeGcsClient) -> None:
    """A GCS object without an MD5 must be flagged as failed without uploading."""
    bucket = gcs_with_objects.bucket("maisys-data-dev")
    bucket.suppress_md5_for.add("raw/a.pdf")

    s3 = FakeS3Client()
    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, s3, config, sleep=lambda _: None)
    manifest = syncer.run()

    entry = next(f for f in manifest.files if f.object_name == "raw/a.pdf")
    assert entry.status == "failed"
    assert entry.error is not None
    assert "MD5" in entry.error
    assert ("maisys-data-prod", "raw/a.pdf") not in s3.store


# ──────────────────────────────────────────────────────────────────────────
# Multipart upload path
# ──────────────────────────────────────────────────────────────────────────
def test_multipart_upload_reconstructs_data_and_etag(gcs_with_objects: FakeGcsClient) -> None:
    """Files larger than the chunked threshold use multipart; final ETag matches."""
    bucket = gcs_with_objects.bucket("maisys-data-dev")
    big = b"x" * 25  # threshold in make_config() is 10 → forces multipart
    bucket.store["raw/big.bin"] = big

    s3 = FakeS3Client()
    config = make_config(source_prefix="raw/")  # block_size=4 → 7 parts (4+4+4+4+4+4+1)
    syncer = Syncer(gcs_with_objects, s3, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert s3.store[("maisys-data-prod", "raw/big.bin")] == big
    entry = next(f for f in manifest.files if f.object_name == "raw/big.bin")
    assert entry.status == "synced"
    # Stored ETag must be in <hex>-<N> form (multipart).
    stored_etag = s3.stored_etags[("maisys-data-prod", "raw/big.bin")]
    assert is_multipart_etag(stored_etag)


def test_multipart_etag_mismatch_retried(gcs_with_objects: FakeGcsClient) -> None:
    bucket = gcs_with_objects.bucket("maisys-data-dev")
    big = b"y" * 30
    bucket.store["raw/big.bin"] = big

    s3 = FakeS3Client()
    s3.corrupt_uploads_for["raw/big.bin"] = 1  # corrupt once, then succeed

    config = make_config(source_prefix="raw/", retry_attempts=3)
    syncer = Syncer(gcs_with_objects, s3, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.failed_count == 0
    entry = next(f for f in manifest.files if f.object_name == "raw/big.bin")
    assert entry.attempts == 2
    assert s3.store[("maisys-data-prod", "raw/big.bin")] == big


def test_multipart_upload_aborts_on_part_failure(gcs_with_objects: FakeGcsClient) -> None:
    """A failed upload_part must trigger abort_multipart_upload (no orphaned parts)."""
    bucket = gcs_with_objects.bucket("maisys-data-dev")
    big = b"z" * 20
    bucket.store["raw/big.bin"] = big

    s3 = FakeS3Client()
    s3.fail_uploads_for.add("raw/big.bin")  # every upload_part fails

    config = make_config(source_prefix="raw/", retry_attempts=2)
    syncer = Syncer(gcs_with_objects, s3, config, sleep=lambda _: None)
    manifest = syncer.run()

    entry = next(f for f in manifest.files if f.object_name == "raw/big.bin")
    assert entry.status == "failed"
    # One abort per retry attempt.
    assert len(s3.aborted_uploads) == 2


# ──────────────────────────────────────────────────────────────────────────
# Exception types
# ──────────────────────────────────────────────────────────────────────────
def test_etag_mismatch_error_is_exception() -> None:
    assert issubclass(EtagMismatchError, Exception)


# ──────────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ──────────────────────────────────────────────────────────────────────────
def _install_main_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gcs: FakeGcsClient,
    s3: FakeS3Client,
    secret_payload: str | None = _secret_payload(),
) -> None:
    monkeypatch.setattr(
        "cloud.sync_gcs_to_aws.get_application_default_credentials",
        lambda *a, **k: (object(), "maisys-dev"),
    )
    secrets: dict[str, str] = {}
    if secret_payload is not None:
        secrets["projects/maisys-dev/secrets/aws-credentials/versions/latest"] = secret_payload
    fake_secret = FakeSecretClient(secrets=secrets)
    monkeypatch.setattr(
        "cloud.sync_gcs_to_aws.secretmanager.SecretManagerServiceClient",
        lambda *a, **k: fake_secret,
    )
    monkeypatch.setattr("cloud.sync_gcs_to_aws.storage.Client", lambda *a, **k: gcs)
    monkeypatch.setattr("cloud.sync_gcs_to_aws.build_aws_client", lambda *a, **k: s3)


def test_main_dry_run_exits_zero(
    monkeypatch: pytest.MonkeyPatch, gcs_with_objects: FakeGcsClient
) -> None:
    s3 = FakeS3Client()
    _install_main_fakes(monkeypatch, gcs=gcs_with_objects, s3=s3)
    rc = main(
        [
            "--source",
            "gs://maisys-data-dev/",
            "--target-bucket",
            "maisys-data-prod",
            "--parallel",
            "2",
            "--prefix",
            "raw/",
            "--dry-run",
        ]
    )
    assert rc == 0
    assert s3.store == {}


def test_main_real_run_writes_manifest(
    monkeypatch: pytest.MonkeyPatch, gcs_with_objects: FakeGcsClient
) -> None:
    s3 = FakeS3Client()
    _install_main_fakes(monkeypatch, gcs=gcs_with_objects, s3=s3)
    rc = main(
        [
            "--source",
            "gs://maisys-data-dev/",
            "--target-bucket",
            "maisys-data-prod",
            "--parallel",
            "2",
            "--prefix",
            "raw/",
        ]
    )
    assert rc == 0
    bucket_store = gcs_with_objects.bucket("maisys-data-dev").store
    assert any(k.startswith("manifests/sync_to_aws_") for k in bucket_store)


def test_main_missing_secret_returns_two(
    monkeypatch: pytest.MonkeyPatch, gcs_with_objects: FakeGcsClient
) -> None:
    s3 = FakeS3Client()
    _install_main_fakes(monkeypatch, gcs=gcs_with_objects, s3=s3, secret_payload=None)
    rc = main(
        [
            "--source",
            "gs://maisys-data-dev/",
            "--target-bucket",
            "maisys-data-prod",
        ]
    )
    assert rc == 2


def test_main_bad_source_uri_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    rc = main(
        [
            "--source",
            "s3://wrong-scheme/",
            "--target-bucket",
            "maisys-data-prod",
        ]
    )
    assert rc == 2


def test_main_failed_files_return_one(
    monkeypatch: pytest.MonkeyPatch, gcs_with_objects: FakeGcsClient
) -> None:
    s3 = FakeS3Client()
    s3.fail_uploads_for.add("raw/a.pdf")
    _install_main_fakes(monkeypatch, gcs=gcs_with_objects, s3=s3)
    rc = main(
        [
            "--source",
            "gs://maisys-data-dev/",
            "--target-bucket",
            "maisys-data-prod",
            "--parallel",
            "2",
            "--prefix",
            "raw/",
            "--retry-attempts",
            "1",
        ]
    )
    assert rc == 1
