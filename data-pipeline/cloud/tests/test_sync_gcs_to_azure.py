"""Tests for ``sync_gcs_to_azure``.

Neither GCS nor Azure is contacted: small in-memory fakes
(:class:`FakeGcsClient`, :class:`FakeAzureServiceClient`, :class:`FakeSecretClient`)
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
from google.api_core import exceptions as gcp_exceptions
from pydantic import ValidationError

from cloud.sync_gcs_to_azure import (
    AzureCredentials,
    AzureSecretMissingError,
    Md5MismatchError,
    SyncConfig,
    Syncer,
    azure_blob_url,
    fetch_azure_credentials,
    join_prefix,
    main,
    parse_gs_uri,
)


# ──────────────────────────────────────────────────────────────────────────
# In-memory fakes
# ──────────────────────────────────────────────────────────────────────────
def _b64_md5(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode("ascii")


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
        # Names for which md5_hash should report ``None`` (simulates composite objects).
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


class _AzureContentSettings:
    def __init__(self, content_md5: bytes | None) -> None:
        self.content_md5 = content_md5


class _AzureBlobProperties:
    def __init__(self, content_md5: bytes | None) -> None:
        self.content_settings = _AzureContentSettings(content_md5)


class FakeAzureBlobClient:
    """Stand-in for ``azure.storage.blob.BlobClient``."""

    def __init__(self, container: FakeAzureContainerClient, blob_name: str) -> None:
        self._container = container
        self.blob_name = blob_name

    def get_blob_properties(self) -> _AzureBlobProperties:
        if self.blob_name not in self._container.store:
            raise gcp_exceptions.NotFound("not found")  # type: ignore[no-untyped-call]
        return _AzureBlobProperties(self._container.md5s.get(self.blob_name))

    def upload_blob(
        self, data: bytes, overwrite: bool = False, content_settings: Any = None
    ) -> None:
        if self.blob_name in self._container.fail_uploads_for:
            self._container.attempts[self.blob_name] = (
                self._container.attempts.get(self.blob_name, 0) + 1
            )
            raise RuntimeError(f"injected upload failure for {self.blob_name}")
        if self._container.corrupt_uploads_for.get(self.blob_name, 0) > 0:
            self._container.corrupt_uploads_for[self.blob_name] -= 1
            corrupt = b"corrupted-bytes"
            self._container.store[self.blob_name] = corrupt
            # Real Azure stores the MD5 of what's actually persisted — that's the
            # value get_blob_properties() must return so the SUT detects the lie.
            self._container.md5s[self.blob_name] = hashlib.md5(corrupt).digest()
            return
        self._container.store[self.blob_name] = data
        claimed = content_settings.content_md5 if content_settings is not None else None
        self._container.md5s[self.blob_name] = bytes(claimed) if claimed is not None else None

    def stage_block(self, block_id: str, data: bytes) -> None:
        if self.blob_name in self._container.fail_uploads_for:
            self._container.attempts[self.blob_name] = (
                self._container.attempts.get(self.blob_name, 0) + 1
            )
            raise RuntimeError(f"injected stage_block failure for {self.blob_name}")
        self._container.staged_blocks.setdefault(self.blob_name, {})[block_id] = data

    def commit_block_list(self, block_ids: list[str], content_settings: Any = None) -> None:
        blocks = self._container.staged_blocks.get(self.blob_name, {})
        ordered = b"".join(blocks[bid] for bid in block_ids)
        if self._container.corrupt_uploads_for.get(self.blob_name, 0) > 0:
            self._container.corrupt_uploads_for[self.blob_name] -= 1
            ordered = b"corrupted-chunked-bytes"
            self._container.store[self.blob_name] = ordered
            self._container.md5s[self.blob_name] = hashlib.md5(ordered).digest()
        else:
            self._container.store[self.blob_name] = ordered
            claimed = content_settings.content_md5 if content_settings is not None else None
            self._container.md5s[self.blob_name] = bytes(claimed) if claimed is not None else None
        # Clear staged blocks after a commit (successful or corrupted).
        self._container.staged_blocks.pop(self.blob_name, None)


class FakeAzureContainerClient:
    """Stand-in for ``azure.storage.blob.ContainerClient``."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.store: dict[str, bytes] = {}
        self.md5s: dict[str, bytes | None] = {}
        self.staged_blocks: dict[str, dict[str, bytes]] = {}
        self.fail_uploads_for: set[str] = set()
        self.corrupt_uploads_for: dict[str, int] = {}
        self.attempts: dict[str, int] = {}

    def get_blob_client(self, blob_name: str) -> FakeAzureBlobClient:
        return FakeAzureBlobClient(self, blob_name)


class FakeAzureServiceClient:
    """Stand-in for ``azure.storage.blob.BlobServiceClient``."""

    def __init__(self) -> None:
        self.containers: dict[str, FakeAzureContainerClient] = {}

    def get_container_client(self, name: str) -> FakeAzureContainerClient:
        return self.containers.setdefault(name, FakeAzureContainerClient(name))


# Patch in: ``FakeAzureBlobClient.get_blob_properties`` raises gcp_exceptions.NotFound
# above, but the real code catches ``azure.core.exceptions.ResourceNotFoundError``.
# We monkeypatch the imported symbol in the SUT so the fake's signal is caught.
# This keeps the fake light (no azure SDK in the test dependency closure when
# focused on a single behaviour).
class _FakeResourceNotFoundError(Exception):
    pass


# Override the FakeAzureBlobClient.get_blob_properties to use the right exception
def _patched_get_blob_properties(self: FakeAzureBlobClient) -> _AzureBlobProperties:
    if self.blob_name not in self._container.store:
        raise _FakeResourceNotFoundError("not found")
    return _AzureBlobProperties(self._container.md5s.get(self.blob_name))


FakeAzureBlobClient.get_blob_properties = _patched_get_blob_properties  # type: ignore[method-assign]


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
@pytest.fixture(autouse=True)
def _patch_resource_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the SUT catch our fake NotFound when probing Azure blob properties."""
    monkeypatch.setattr("cloud.sync_gcs_to_azure.ResourceNotFoundError", _FakeResourceNotFoundError)


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
        "target_account": "maisysstage",
        "target_container": "maisys-data-stage",
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
    # Whitespace-only / empty fragments are discarded
    assert join_prefix("/", None) == ""


def test_azure_blob_url() -> None:
    assert azure_blob_url("acct", "cont", "raw/a.pdf") == (
        "https://acct.blob.core.windows.net/cont/raw/a.pdf"
    )


# ──────────────────────────────────────────────────────────────────────────
# Config model
# ──────────────────────────────────────────────────────────────────────────
def test_sync_config_rejects_zero_parallel() -> None:
    with pytest.raises(ValidationError):
        make_config(parallel=0)


def test_sync_config_rejects_zero_retry_attempts() -> None:
    with pytest.raises(ValidationError):
        make_config(retry_attempts=0)


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
    assert creds.storage_account == "acct"


def test_azure_credentials_reject_missing_keys() -> None:
    with pytest.raises(ValidationError):
        AzureCredentials.model_validate({"tenantId": "t"})


# ──────────────────────────────────────────────────────────────────────────
# Secret Manager integration
# ──────────────────────────────────────────────────────────────────────────
def _secret_payload() -> str:
    return json.dumps(
        {
            "tenantId": "tenant-uuid",
            "clientId": "client-uuid",
            "clientSecret": "shhh",
            "subscriptionId": "sub-uuid",
            "storageAccount": "maisysstage",
        }
    )


def test_fetch_azure_credentials_happy_path() -> None:
    secret_key = "projects/maisys-dev/secrets/azure-service-principal/versions/latest"
    client = FakeSecretClient(secrets={secret_key: _secret_payload()})
    creds = fetch_azure_credentials(client, "maisys-dev")
    assert creds.tenant_id == "tenant-uuid"


def test_fetch_azure_credentials_missing_raises_with_remediation() -> None:
    client = FakeSecretClient(secrets={})
    with pytest.raises(AzureSecretMissingError) as exc_info:
        fetch_azure_credentials(client, "maisys-dev")
    msg = str(exc_info.value)
    assert "azure-service-principal" in msg
    assert "maisys-dev" in msg
    # The error must include a concrete gcloud command to create the secret.
    assert "gcloud secrets create azure-service-principal" in msg
    assert "gcloud secrets versions add azure-service-principal" in msg
    assert "--project=maisys-dev" in msg


def test_fetch_azure_credentials_invalid_json_raises() -> None:
    client = FakeSecretClient(
        secrets={"projects/p/secrets/azure-service-principal/versions/latest": "{not json"}
    )
    with pytest.raises(ValueError):
        fetch_azure_credentials(client, "p")


def test_fetch_azure_credentials_missing_keys_raises() -> None:
    client = FakeSecretClient(
        secrets={
            "projects/p/secrets/azure-service-principal/versions/latest": json.dumps(
                {"tenantId": "t"}
            )
        }
    )
    with pytest.raises(ValidationError):
        fetch_azure_credentials(client, "p")


# ──────────────────────────────────────────────────────────────────────────
# Skip / force / dry-run
# ──────────────────────────────────────────────────────────────────────────
def test_full_run_syncs_all_and_writes_manifest(gcs_with_objects: FakeGcsClient) -> None:
    azure = FakeAzureServiceClient()
    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, azure, config, sleep=lambda _: None)

    manifest = syncer.run()
    assert manifest.total_files == 3
    assert manifest.synced_count == 3
    assert manifest.failed_count == 0
    assert manifest.skipped_count == 0

    container = azure.get_container_client("maisys-data-stage")
    assert container.store["raw/a.pdf"] == b"alpha"
    assert container.store["raw/sub/c.pdf"] == b"charlie"
    # The beta_training object is outside the prefix and must not have been touched.
    assert "beta_training/x.jsonl" not in container.store

    uri = syncer.write_manifest(manifest)
    assert uri.startswith("gs://maisys-data-dev/manifests/sync_to_azure_")
    bucket_store = gcs_with_objects.bucket("maisys-data-dev").store
    manifest_object = f"manifests/sync_to_azure_{manifest.run_id}.json"
    written = json.loads(bucket_store[manifest_object].decode("utf-8"))
    assert written["run_id"] == manifest.run_id
    assert written["synced_count"] == 3
    assert written["failed_count"] == 0


def test_skip_if_md5_matches(gcs_with_objects: FakeGcsClient) -> None:
    azure = FakeAzureServiceClient()
    container = azure.get_container_client("maisys-data-stage")
    # Pre-seed one Azure blob with matching content + correct MD5 → should be skipped.
    container.store["raw/a.pdf"] = b"alpha"
    container.md5s["raw/a.pdf"] = hashlib.md5(b"alpha").digest()

    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, azure, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.skipped_count == 1
    assert manifest.synced_count == 2
    assert manifest.failed_count == 0


def test_stale_md5_is_not_skipped(gcs_with_objects: FakeGcsClient) -> None:
    azure = FakeAzureServiceClient()
    container = azure.get_container_client("maisys-data-stage")
    # Azure already has a blob but with WRONG content / WRONG MD5.
    container.store["raw/a.pdf"] = b"STALE"
    container.md5s["raw/a.pdf"] = hashlib.md5(b"STALE").digest()

    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, azure, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.synced_count == 3
    assert manifest.skipped_count == 0
    # After sync the Azure blob should now hold the source bytes.
    assert container.store["raw/a.pdf"] == b"alpha"


def test_force_reuploads_even_when_md5_matches(gcs_with_objects: FakeGcsClient) -> None:
    azure = FakeAzureServiceClient()
    container = azure.get_container_client("maisys-data-stage")
    container.store["raw/a.pdf"] = b"alpha"
    container.md5s["raw/a.pdf"] = hashlib.md5(b"alpha").digest()

    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, azure, config, force=True, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.skipped_count == 0
    assert manifest.synced_count == 3


def test_dry_run_does_not_upload(gcs_with_objects: FakeGcsClient) -> None:
    azure = FakeAzureServiceClient()
    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, azure, config, dry_run=True, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.synced_count == 3
    container = azure.get_container_client("maisys-data-stage")
    assert container.store == {}


def test_prefix_narrowing(gcs_with_objects: FakeGcsClient) -> None:
    azure = FakeAzureServiceClient()
    config = make_config(source_prefix="raw/sub/")
    syncer = Syncer(gcs_with_objects, azure, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.total_files == 1
    assert manifest.synced_count == 1
    container = azure.get_container_client("maisys-data-stage")
    assert list(container.store) == ["raw/sub/c.pdf"]


# ──────────────────────────────────────────────────────────────────────────
# Retry behaviour
# ──────────────────────────────────────────────────────────────────────────
def test_md5_mismatch_retried_then_succeeds(gcs_with_objects: FakeGcsClient) -> None:
    azure = FakeAzureServiceClient()
    container = azure.get_container_client("maisys-data-stage")
    # First upload of raw/a.pdf will land "corrupted" → MD5 mismatch → retry → success.
    container.corrupt_uploads_for["raw/a.pdf"] = 1

    config = make_config(source_prefix="raw/", retry_attempts=3)
    syncer = Syncer(gcs_with_objects, azure, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.failed_count == 0
    assert manifest.synced_count == 3
    entry = next(f for f in manifest.files if f.object_name == "raw/a.pdf")
    assert entry.status == "synced"
    assert entry.attempts == 2
    assert container.store["raw/a.pdf"] == b"alpha"


def test_md5_mismatch_exhausts_retries_and_fails(gcs_with_objects: FakeGcsClient) -> None:
    azure = FakeAzureServiceClient()
    container = azure.get_container_client("maisys-data-stage")
    # Corrupt every attempt → all retries see a mismatch.
    container.corrupt_uploads_for["raw/a.pdf"] = 99

    config = make_config(source_prefix="raw/", retry_attempts=3)
    syncer = Syncer(gcs_with_objects, azure, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.failed_count == 1
    entry = next(f for f in manifest.files if f.object_name == "raw/a.pdf")
    assert entry.status == "failed"
    assert entry.attempts == 3
    assert entry.error is not None


def test_partial_failure_run(gcs_with_objects: FakeGcsClient) -> None:
    azure = FakeAzureServiceClient()
    container = azure.get_container_client("maisys-data-stage")
    container.fail_uploads_for.add("raw/a.pdf")  # only this one fails

    config = make_config(source_prefix="raw/", retry_attempts=2)
    syncer = Syncer(gcs_with_objects, azure, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.synced_count == 2
    assert manifest.failed_count == 1
    assert manifest.failed_files == ["raw/a.pdf"]


def test_source_md5_missing_is_failure(gcs_with_objects: FakeGcsClient) -> None:
    """A GCS object without an MD5 must be flagged as failed without uploading."""
    bucket = gcs_with_objects.bucket("maisys-data-dev")
    bucket.suppress_md5_for.add("raw/a.pdf")

    azure = FakeAzureServiceClient()
    config = make_config(source_prefix="raw/")
    syncer = Syncer(gcs_with_objects, azure, config, sleep=lambda _: None)
    manifest = syncer.run()

    entry = next(f for f in manifest.files if f.object_name == "raw/a.pdf")
    assert entry.status == "failed"
    assert entry.error is not None
    assert "MD5" in entry.error
    container = azure.get_container_client("maisys-data-stage")
    # File without source MD5 must not land in Azure.
    assert "raw/a.pdf" not in container.store


# ──────────────────────────────────────────────────────────────────────────
# Chunked upload path
# ──────────────────────────────────────────────────────────────────────────
def test_chunked_upload_reconstructs_data(gcs_with_objects: FakeGcsClient) -> None:
    """Files larger than the chunked threshold are uploaded via stage_block + commit."""
    bucket = gcs_with_objects.bucket("maisys-data-dev")
    big = b"x" * 25  # 25 bytes; threshold in make_config() is 10 → forces chunked path
    bucket.store["raw/big.bin"] = big

    azure = FakeAzureServiceClient()
    config = make_config(source_prefix="raw/")  # block_size_bytes=4, chunked_threshold_bytes=10
    syncer = Syncer(gcs_with_objects, azure, config, sleep=lambda _: None)
    manifest = syncer.run()

    container = azure.get_container_client("maisys-data-stage")
    assert container.store["raw/big.bin"] == big
    entry = next(f for f in manifest.files if f.object_name == "raw/big.bin")
    assert entry.status == "synced"


def test_chunked_upload_md5_mismatch_retried(gcs_with_objects: FakeGcsClient) -> None:
    bucket = gcs_with_objects.bucket("maisys-data-dev")
    big = b"y" * 30
    bucket.store["raw/big.bin"] = big

    azure = FakeAzureServiceClient()
    container = azure.get_container_client("maisys-data-stage")
    container.corrupt_uploads_for["raw/big.bin"] = 1  # corrupt once, then succeed

    config = make_config(source_prefix="raw/", retry_attempts=3)
    syncer = Syncer(gcs_with_objects, azure, config, sleep=lambda _: None)
    manifest = syncer.run()

    assert manifest.failed_count == 0
    entry = next(f for f in manifest.files if f.object_name == "raw/big.bin")
    assert entry.attempts == 2
    assert container.store["raw/big.bin"] == big


# ──────────────────────────────────────────────────────────────────────────
# Md5MismatchError type
# ──────────────────────────────────────────────────────────────────────────
def test_md5_mismatch_error_is_exception() -> None:
    assert issubclass(Md5MismatchError, Exception)


# ──────────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ──────────────────────────────────────────────────────────────────────────
def _install_main_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gcs: FakeGcsClient,
    azure: FakeAzureServiceClient,
    secret_payload: str | None = _secret_payload(),
) -> None:
    """Monkey-patch every external client constructor used by ``main()``."""
    monkeypatch.setattr(
        "cloud.sync_gcs_to_azure.get_application_default_credentials",
        lambda *a, **k: (object(), "maisys-dev"),
    )
    secrets: dict[str, str] = {}
    if secret_payload is not None:
        secrets["projects/maisys-dev/secrets/azure-service-principal/versions/latest"] = (
            secret_payload
        )
    fake_secret = FakeSecretClient(secrets=secrets)
    monkeypatch.setattr(
        "cloud.sync_gcs_to_azure.secretmanager.SecretManagerServiceClient",
        lambda *a, **k: fake_secret,
    )
    monkeypatch.setattr("cloud.sync_gcs_to_azure.storage.Client", lambda *a, **k: gcs)
    monkeypatch.setattr(
        "cloud.sync_gcs_to_azure.build_azure_client",
        lambda *a, **k: azure,
    )


def test_main_dry_run_exits_zero(
    monkeypatch: pytest.MonkeyPatch, gcs_with_objects: FakeGcsClient
) -> None:
    azure = FakeAzureServiceClient()
    _install_main_fakes(monkeypatch, gcs=gcs_with_objects, azure=azure)
    rc = main(
        [
            "--source",
            "gs://maisys-data-dev/",
            "--target-account",
            "maisysstage",
            "--target-container",
            "maisys-data-stage",
            "--parallel",
            "2",
            "--prefix",
            "raw/",
            "--dry-run",
        ]
    )
    assert rc == 0
    container = azure.get_container_client("maisys-data-stage")
    assert container.store == {}


def test_main_real_run_writes_manifest(
    monkeypatch: pytest.MonkeyPatch, gcs_with_objects: FakeGcsClient
) -> None:
    azure = FakeAzureServiceClient()
    _install_main_fakes(monkeypatch, gcs=gcs_with_objects, azure=azure)
    rc = main(
        [
            "--source",
            "gs://maisys-data-dev/",
            "--target-account",
            "maisysstage",
            "--target-container",
            "maisys-data-stage",
            "--parallel",
            "2",
            "--prefix",
            "raw/",
        ]
    )
    assert rc == 0
    bucket_store = gcs_with_objects.bucket("maisys-data-dev").store
    assert any(k.startswith("manifests/sync_to_azure_") for k in bucket_store)


def test_main_missing_secret_returns_two(
    monkeypatch: pytest.MonkeyPatch, gcs_with_objects: FakeGcsClient
) -> None:
    azure = FakeAzureServiceClient()
    _install_main_fakes(monkeypatch, gcs=gcs_with_objects, azure=azure, secret_payload=None)
    rc = main(
        [
            "--source",
            "gs://maisys-data-dev/",
            "--target-account",
            "maisysstage",
            "--target-container",
            "maisys-data-stage",
        ]
    )
    assert rc == 2


def test_main_bad_source_uri_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    # We never reach auth — the source URI rejects first.
    rc = main(
        [
            "--source",
            "s3://wrong-scheme/",
            "--target-account",
            "maisysstage",
            "--target-container",
            "maisys-data-stage",
        ]
    )
    assert rc == 2


def test_main_failed_files_return_one(
    monkeypatch: pytest.MonkeyPatch, gcs_with_objects: FakeGcsClient
) -> None:
    azure = FakeAzureServiceClient()
    container = azure.get_container_client("maisys-data-stage")
    container.fail_uploads_for.add("raw/a.pdf")
    _install_main_fakes(monkeypatch, gcs=gcs_with_objects, azure=azure)
    rc = main(
        [
            "--source",
            "gs://maisys-data-dev/",
            "--target-account",
            "maisysstage",
            "--target-container",
            "maisys-data-stage",
            "--parallel",
            "2",
            "--prefix",
            "raw/",
            "--retry-attempts",
            "1",
        ]
    )
    assert rc == 1
