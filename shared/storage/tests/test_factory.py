"""Tests for shared.storage.factory.

No async, no SDK calls — purely the URI / env-var dispatch logic. The
factory's job is to return the right concrete backend; instantiating that
backend is enough to prove dispatch worked (the backend constructors
themselves are mocked in the per-backend tests).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from shared.storage import (
    AWSStorageClient,
    AzureStorageClient,
    GCSStorageClient,
    StorageClient,
)


# ──────────────────────────────────────────────────────────────────────────
# GCS's storage.Client() triggers Application Default Credentials lookup at
# construction time. In CI we have no ADC, so we stub it out for the whole
# module. AzureStorageClient and AWSStorageClient defer credential lookup to
# the first SDK call and need no stub here.
# ──────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _no_gcs_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "shared.storage.gcs.storage.Client",
        lambda *args, **kwargs: MagicMock(name="stub-gcs-client"),
    )


# ──────────────────────────────────────────────────────────────────────────
# from_uri — happy paths
# ──────────────────────────────────────────────────────────────────────────
class TestFromUriHappy:
    def test_gs_uri(self) -> None:
        client = StorageClient.from_uri("gs://my-bucket/some/path")
        assert isinstance(client, GCSStorageClient)
        assert client._bucket_name == "my-bucket"

    def test_gs_uri_root(self) -> None:
        client = StorageClient.from_uri("gs://my-bucket")
        assert isinstance(client, GCSStorageClient)

    def test_s3_uri(self) -> None:
        client = StorageClient.from_uri("s3://prod-bucket/key.txt")
        assert isinstance(client, AWSStorageClient)
        assert client._bucket == "prod-bucket"

    def test_azure_https_uri(self) -> None:
        client = StorageClient.from_uri(
            "https://maisysstage.blob.core.windows.net/maisys-data-stage/raw/x.json"
        )
        assert isinstance(client, AzureStorageClient)
        assert client._account == "maisysstage"
        assert client._container == "maisys-data-stage"


# ──────────────────────────────────────────────────────────────────────────
# from_uri — rejection cases
# ──────────────────────────────────────────────────────────────────────────
class TestFromUriRejection:
    def test_unknown_scheme(self) -> None:
        with pytest.raises(ValueError, match="Unsupported URI scheme"):
            StorageClient.from_uri("ftp://server/path")

    def test_unknown_scheme_lists_supported_shapes(self) -> None:
        with pytest.raises(ValueError, match=r"gs://bucket/path"):
            StorageClient.from_uri("ftp://server/path")

    def test_https_non_azure_host(self) -> None:
        with pytest.raises(ValueError, match="Unsupported HTTPS host"):
            StorageClient.from_uri("https://example.com/some/path")

    def test_azure_missing_container(self) -> None:
        with pytest.raises(ValueError, match="missing container"):
            StorageClient.from_uri("https://maisysstage.blob.core.windows.net/")

    def test_gs_missing_bucket(self) -> None:
        with pytest.raises(ValueError, match="missing bucket"):
            StorageClient.from_uri("gs://")

    def test_s3_missing_bucket(self) -> None:
        with pytest.raises(ValueError, match="missing bucket"):
            StorageClient.from_uri("s3://")


# ──────────────────────────────────────────────────────────────────────────
# Factory is not directly instantiable
# ──────────────────────────────────────────────────────────────────────────
class TestFactoryIsNotInstantiable:
    def test_direct_instantiation_blocked(self) -> None:
        with pytest.raises(TypeError, match="factory facade"):
            StorageClient()


# ──────────────────────────────────────────────────────────────────────────
# from_env — happy paths
# ──────────────────────────────────────────────────────────────────────────
class TestFromEnvHappy:
    def test_gcp(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        monkeypatch.setenv("STORAGE_BUCKET", "maisys-data-dev")
        client = StorageClient.from_env()
        assert isinstance(client, GCSStorageClient)
        assert client._bucket_name == "maisys-data-dev"

    def test_gcp_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOUD_PROVIDER", "GCP")
        monkeypatch.setenv("STORAGE_BUCKET", "x")
        assert isinstance(StorageClient.from_env(), GCSStorageClient)

    def test_azure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOUD_PROVIDER", "azure")
        monkeypatch.setenv("STORAGE_ACCOUNT", "maisysstage")
        monkeypatch.setenv("STORAGE_CONTAINER", "maisys-data-stage")
        client = StorageClient.from_env()
        assert isinstance(client, AzureStorageClient)
        assert client._account == "maisysstage"
        assert client._container == "maisys-data-stage"

    def test_aws_with_region(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        monkeypatch.setenv("STORAGE_BUCKET", "maisys-data-prod")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        client = StorageClient.from_env()
        assert isinstance(client, AWSStorageClient)
        assert client._bucket == "maisys-data-prod"
        assert client._region == "us-east-1"

    def test_aws_without_region(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        monkeypatch.setenv("STORAGE_BUCKET", "maisys-data-prod")
        monkeypatch.delenv("AWS_REGION", raising=False)
        client = StorageClient.from_env()
        assert isinstance(client, AWSStorageClient)
        assert client._region is None


# ──────────────────────────────────────────────────────────────────────────
# from_env — missing or invalid env vars
# ──────────────────────────────────────────────────────────────────────────
class TestFromEnvFailures:
    def test_cloud_provider_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CLOUD_PROVIDER", raising=False)
        with pytest.raises(RuntimeError, match="CLOUD_PROVIDER is not set"):
            StorageClient.from_env()

    def test_cloud_provider_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOUD_PROVIDER", "azurecat")
        with pytest.raises(RuntimeError, match="azurecat.*is unknown"):
            StorageClient.from_env()

    def test_gcp_missing_bucket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOUD_PROVIDER", "gcp")
        monkeypatch.delenv("STORAGE_BUCKET", raising=False)
        with pytest.raises(RuntimeError, match="STORAGE_BUCKET"):
            StorageClient.from_env()

    def test_azure_missing_account(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOUD_PROVIDER", "azure")
        monkeypatch.delenv("STORAGE_ACCOUNT", raising=False)
        monkeypatch.setenv("STORAGE_CONTAINER", "c")
        with pytest.raises(RuntimeError, match="STORAGE_ACCOUNT"):
            StorageClient.from_env()

    def test_azure_missing_container(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOUD_PROVIDER", "azure")
        monkeypatch.setenv("STORAGE_ACCOUNT", "a")
        monkeypatch.delenv("STORAGE_CONTAINER", raising=False)
        with pytest.raises(RuntimeError, match="STORAGE_CONTAINER"):
            StorageClient.from_env()

    def test_azure_missing_both(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOUD_PROVIDER", "azure")
        monkeypatch.delenv("STORAGE_ACCOUNT", raising=False)
        monkeypatch.delenv("STORAGE_CONTAINER", raising=False)
        with pytest.raises(
            RuntimeError,
            match=r"STORAGE_ACCOUNT and STORAGE_CONTAINER",
        ):
            StorageClient.from_env()

    def test_aws_missing_bucket(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLOUD_PROVIDER", "aws")
        monkeypatch.delenv("STORAGE_BUCKET", raising=False)
        with pytest.raises(RuntimeError, match="STORAGE_BUCKET"):
            StorageClient.from_env()
