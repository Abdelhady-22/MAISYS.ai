"""Tests for the Azure backend.

Two layers (same shape as test_gcs.py):

1. **Protocol conformance** against :class:`FakeAzureStorageClient`.

2. **Azure-specific edge cases** on the real :class:`AzureStorageClient`:
   * ``content_md5`` is exposed as bytes by the SDK; we must convert to
     lowercase hex in BlobInfo.
   * SAS token generation mocks the user-delegation-key call and verifies
     the resulting URL is well-formed.
   * Exception translation for ResourceNotFoundError, 403, 404, auth.
   * URI scope validation (rejects mismatched account/container).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)

from shared.storage import (
    AccessDeniedException,
    AzureStorageClient,
    BlobInfo,
    ObjectNotFoundException,
    StorageException,
)
from shared.storage.tests.conftest import FakeAzureStorageClient


# ══════════════════════════════════════════════════════════════════════════
# Section 1 — Protocol conformance via FakeAzureStorageClient
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def fake() -> FakeAzureStorageClient:
    return FakeAzureStorageClient(account="maisysstage", container="data")


class TestProtocolConformanceAzure:
    @pytest.mark.asyncio
    async def test_read_after_write(self, fake: FakeAzureStorageClient) -> None:
        await fake.write_bytes("hello.txt", b"hello world")
        assert await fake.read_bytes("hello.txt") == b"hello world"

    @pytest.mark.asyncio
    async def test_write_returns_blobinfo_with_md5(self, fake: FakeAzureStorageClient) -> None:
        info = await fake.write_bytes("a.txt", b"abc")
        assert info.size_bytes == 3
        assert info.md5_hex == hashlib.md5(b"abc").hexdigest()
        assert info.uri == "https://maisysstage.blob.core.windows.net/data/a.txt"

    @pytest.mark.asyncio
    async def test_write_records_content_type_and_metadata(
        self, fake: FakeAzureStorageClient
    ) -> None:
        info = await fake.write_bytes(
            "doc.json",
            b'{"k": 1}',
            content_type="application/json",
            metadata={"source": "test"},
        )
        assert info.content_type == "application/json"
        assert info.metadata == {"source": "test"}

    @pytest.mark.asyncio
    async def test_exists(self, fake: FakeAzureStorageClient) -> None:
        assert await fake.exists("nope") is False
        await fake.write_bytes("present.txt", b"x")
        assert await fake.exists("present.txt") is True

    @pytest.mark.asyncio
    async def test_delete_is_idempotent(self, fake: FakeAzureStorageClient) -> None:
        await fake.write_bytes("d.txt", b"x")
        await fake.delete("d.txt")
        await fake.delete("d.txt")
        assert await fake.exists("d.txt") is False

    @pytest.mark.asyncio
    async def test_stat_returns_blobinfo(self, fake: FakeAzureStorageClient) -> None:
        await fake.write_bytes("s.txt", b"abcdef")
        info = await fake.stat("s.txt")
        assert isinstance(info, BlobInfo)
        assert info.size_bytes == 6
        assert info.md5_hex == hashlib.md5(b"abcdef").hexdigest()

    @pytest.mark.asyncio
    async def test_stat_missing_raises(self, fake: FakeAzureStorageClient) -> None:
        with pytest.raises(ObjectNotFoundException):
            await fake.stat("nope")

    @pytest.mark.asyncio
    async def test_read_missing_raises(self, fake: FakeAzureStorageClient) -> None:
        with pytest.raises(ObjectNotFoundException):
            await fake.read_bytes("nope")

    @pytest.mark.asyncio
    async def test_copy_preserves_md5(self, fake: FakeAzureStorageClient) -> None:
        await fake.write_bytes("src.txt", b"copy me please")
        src_info = await fake.stat("src.txt")
        dst_info = await fake.copy("src.txt", "dst.txt")
        assert dst_info.size_bytes == src_info.size_bytes
        assert dst_info.md5_hex == src_info.md5_hex
        assert await fake.read_bytes("dst.txt") == b"copy me please"

    @pytest.mark.asyncio
    async def test_copy_missing_raises(self, fake: FakeAzureStorageClient) -> None:
        with pytest.raises(ObjectNotFoundException):
            await fake.copy("nope", "anywhere")

    @pytest.mark.asyncio
    async def test_list_prefix_iterates(self, fake: FakeAzureStorageClient) -> None:
        for i in range(5):
            await fake.write_bytes(f"raw/file-{i}.txt", f"data{i}".encode())
        await fake.write_bytes("other/x.txt", b"x")
        found = [info.uri async for info in fake.list_prefix("raw/")]
        assert len(found) == 5
        assert all("/raw/" in u for u in found)

    @pytest.mark.asyncio
    async def test_signed_url_nonempty(self, fake: FakeAzureStorageClient) -> None:
        await fake.write_bytes("x.txt", b"x")
        url = await fake.signed_url("x.txt", expires_in=timedelta(minutes=5))
        assert url and url.startswith("https://maisysstage.blob.core.windows.net/data/x.txt")

    @pytest.mark.asyncio
    async def test_uri_path_accepted(self, fake: FakeAzureStorageClient) -> None:
        full = "https://maisysstage.blob.core.windows.net/data/u.txt"
        await fake.write_bytes(full, b"u")
        assert await fake.read_bytes("u.txt") == b"u"
        assert await fake.read_bytes(full) == b"u"

    @pytest.mark.asyncio
    async def test_uri_wrong_account_rejected(self, fake: FakeAzureStorageClient) -> None:
        with pytest.raises(ValueError, match="does not match"):
            await fake.read_bytes("https://otheraccount.blob.core.windows.net/data/x.txt")

    @pytest.mark.asyncio
    async def test_uri_wrong_container_rejected(self, fake: FakeAzureStorageClient) -> None:
        with pytest.raises(ValueError, match="does not match"):
            await fake.read_bytes("https://maisysstage.blob.core.windows.net/wrong/x.txt")

    @pytest.mark.asyncio
    async def test_access_denied_surfaces(self, fake: FakeAzureStorageClient) -> None:
        fake.deny_access_to("secret.txt")
        with pytest.raises(AccessDeniedException):
            await fake.read_bytes("secret.txt")


# ══════════════════════════════════════════════════════════════════════════
# Section 2 — Azure-specific edge cases (real AzureStorageClient)
# ══════════════════════════════════════════════════════════════════════════
def _real() -> AzureStorageClient:
    """Construct a real client with a stub credential so we don't touch AAD."""
    return AzureStorageClient(
        account="maisysstage",
        container="data",
        credential=MagicMock(name="stub-credential"),
    )


class TestMd5BytesToHex:
    """Azure exposes content_md5 as bytes — verify it surfaces as lowercase hex."""

    def test_16_byte_md5_converts_to_hex(self) -> None:
        digest = hashlib.md5(b"hello").digest()  # 16 bytes
        props = SimpleNamespace(
            size=5,
            last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
            content_settings=SimpleNamespace(
                content_type="text/plain",
                content_md5=bytearray(digest),
            ),
            metadata={"k": "v"},
        )
        client = _real()
        info = client._blob_info_from_props("hello.txt", props)
        assert info.md5_hex == digest.hex()
        assert info.size_bytes == 5
        assert info.content_type == "text/plain"
        assert info.metadata == {"k": "v"}

    def test_missing_md5_yields_none(self) -> None:
        props = SimpleNamespace(
            size=0,
            last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
            content_settings=SimpleNamespace(content_type=None, content_md5=None),
            metadata=None,
        )
        info = _real()._blob_info_from_props("empty.txt", props)
        assert info.md5_hex is None
        assert info.metadata == {}

    def test_wrong_length_md5_yields_none(self) -> None:
        # Backend sometimes returns a non-16-byte value when the upload
        # didn't compute content_md5. Treat as "no hash available".
        props = SimpleNamespace(
            size=4,
            last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
            content_settings=SimpleNamespace(content_type=None, content_md5=bytearray(b"short")),
            metadata=None,
        )
        info = _real()._blob_info_from_props("x.txt", props)
        assert info.md5_hex is None

    def test_naive_datetime_is_assumed_utc(self) -> None:
        props = SimpleNamespace(
            size=0,
            last_modified=datetime(2026, 1, 1),  # no tz
            content_settings=SimpleNamespace(content_type=None, content_md5=None),
            metadata=None,
        )
        info = _real()._blob_info_from_props("x.txt", props)
        assert info.last_modified.tzinfo is timezone.utc


class TestExceptionTranslation:
    @pytest.mark.parametrize(
        "exc, expected_cls",
        [
            (ResourceNotFoundError("x"), ObjectNotFoundException),
            (ClientAuthenticationError("x"), AccessDeniedException),
            (
                HttpResponseError(response=MagicMock(status_code=403)),
                AccessDeniedException,
            ),
            (
                HttpResponseError(response=MagicMock(status_code=404)),
                ObjectNotFoundException,
            ),
            (RuntimeError("unknown"), StorageException),
        ],
    )
    def test_translate_maps_sdk_exception(
        self, exc: BaseException, expected_cls: type[StorageException]
    ) -> None:
        translated = AzureStorageClient._translate("path", exc)
        assert isinstance(translated, expected_cls)
        assert translated.cause is exc


class TestUriResolution:
    def test_bare_path(self) -> None:
        client = _real()
        assert client._resolve_path("foo/bar.txt") == "foo/bar.txt"

    def test_full_uri(self) -> None:
        client = _real()
        full = "https://maisysstage.blob.core.windows.net/data/foo/bar.txt"
        assert client._resolve_path(full) == "foo/bar.txt"

    def test_wrong_account(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            _real()._resolve_path("https://otheracct.blob.core.windows.net/data/x.txt")

    def test_wrong_container(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            _real()._resolve_path("https://maisysstage.blob.core.windows.net/wrong/x.txt")

    def test_non_azure_https_rejected(self) -> None:
        with pytest.raises(ValueError, match="does not look like"):
            _real()._resolve_path("https://example.com/some/path")


class TestSasGeneration:
    @pytest.mark.asyncio
    async def test_signed_url_get(self) -> None:
        """generate_blob_sas should be called and concatenated into the URL."""
        client = _real()
        # Mock the user-delegation-key fetch and the SAS generator.
        udk = MagicMock(name="user-delegation-key")
        with (
            patch.object(
                client._service,
                "get_user_delegation_key",
                new=AsyncMock(return_value=udk),
            ),
            patch(
                "shared.storage.azure.generate_blob_sas",
                return_value="sv=2025-01-05&sig=fakeSIG",
            ) as mock_gen,
        ):
            url = await client.signed_url("path/to/blob.txt", timedelta(minutes=10))
        assert url.endswith("?sv=2025-01-05&sig=fakeSIG")
        assert "https://maisysstage.blob.core.windows.net/data/path/to/blob.txt" in url
        # Verify the SAS generator received the right inputs.
        call = mock_gen.call_args
        assert call.kwargs["account_name"] == "maisysstage"
        assert call.kwargs["container_name"] == "data"
        assert call.kwargs["blob_name"] == "path/to/blob.txt"
        assert call.kwargs["user_delegation_key"] is udk

    @pytest.mark.asyncio
    async def test_signed_url_invalid_method(self) -> None:
        with pytest.raises(ValueError, match="supports only GET or PUT"):
            await _real().signed_url("x.txt", timedelta(minutes=10), method="DELETE")

    @pytest.mark.asyncio
    async def test_signed_url_translates_sdk_error(self) -> None:
        client = _real()
        with patch.object(
            client._service,
            "get_user_delegation_key",
            new=AsyncMock(side_effect=ClientAuthenticationError("nope")),
        ):
            with pytest.raises(AccessDeniedException):
                await client.signed_url("x.txt", timedelta(minutes=10))


# ──────────────────────────────────────────────────────────────────────────
# Azure SDK end-to-end via mocked container / blob clients.
# Builds a single fake container client wired into the real
# AzureStorageClient so read_bytes / write_bytes / list_prefix / etc. all
# exercise the real translation logic.
# ──────────────────────────────────────────────────────────────────────────
class _FakeDownloader:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def readall(self) -> bytes:
        return self._data


class _AzureFakeAsyncIter:
    """Wraps a list of blob-prop objects to satisfy the SDK's async iter protocol."""

    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def __aiter__(self) -> "_AzureFakeAsyncIter":
        self._idx = 0
        return self

    async def __anext__(self) -> Any:
        if self._idx >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._idx]
        self._idx += 1
        return item


def _props(
    *,
    size: int = 0,
    md5_bytes: bytes | None = None,
    content_type: str | None = None,
    metadata: dict[str, str] | None = None,
    name: str | None = None,
) -> SimpleNamespace:
    cs = SimpleNamespace(content_type=content_type, content_md5=md5_bytes)
    obj = SimpleNamespace(
        size=size,
        last_modified=datetime(2026, 1, 1, tzinfo=timezone.utc),
        content_settings=cs,
        metadata=metadata or {},
    )
    if name is not None:
        obj.name = name
    return obj


class _FakeBlobClient:
    def __init__(self, name: str, container: "_FakeContainerClient") -> None:
        self.name = name
        self._container = container
        self.url = (
            f"https://{container._account}.blob.core.windows.net/" f"{container._container}/{name}"
        )

    async def download_blob(self) -> _FakeDownloader:
        if self.name not in self._container._store:
            raise ResourceNotFoundError(f"missing: {self.name}")
        return _FakeDownloader(self._container._store[self.name]["data"])

    async def upload_blob(
        self,
        data: bytes,
        overwrite: bool = False,
        content_settings: Any = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self._container._store[self.name] = {
            "data": bytes(data),
            "content_type": getattr(content_settings, "content_type", None),
            "metadata": dict(metadata or {}),
        }

    async def get_blob_properties(self) -> SimpleNamespace:
        entry = self._container._store.get(self.name)
        if entry is None:
            raise ResourceNotFoundError(f"missing: {self.name}")
        return _props(
            size=len(entry["data"]),
            md5_bytes=hashlib.md5(entry["data"]).digest(),
            content_type=entry.get("content_type"),
            metadata=entry.get("metadata"),
        )

    async def exists(self) -> bool:
        return self.name in self._container._store

    async def delete_blob(self) -> None:
        if self.name not in self._container._store:
            raise ResourceNotFoundError(f"missing: {self.name}")
        del self._container._store[self.name]

    async def start_copy_from_url(self, source_url: str, requires_sync: bool = False) -> None:
        # source_url ends with "/<account>/<container>/<src_name>".
        src_name = source_url.rsplit("/", 1)[-1]
        if src_name not in self._container._store:
            raise ResourceNotFoundError(f"missing: {src_name}")
        self._container._store[self.name] = dict(self._container._store[src_name])


class _FakeContainerClient:
    def __init__(self, account: str, container: str) -> None:
        self._account = account
        self._container = container
        self._store: dict[str, dict[str, Any]] = {}

    def get_blob_client(self, name: str) -> _FakeBlobClient:
        return _FakeBlobClient(name, self)

    def list_blobs(self, name_starts_with: str = "") -> _AzureFakeAsyncIter:
        items = []
        for name, entry in sorted(self._store.items()):
            if name.startswith(name_starts_with):
                items.append(
                    _props(
                        size=len(entry["data"]),
                        md5_bytes=hashlib.md5(entry["data"]).digest(),
                        content_type=entry.get("content_type"),
                        metadata=entry.get("metadata"),
                        name=name,
                    )
                )
        return _AzureFakeAsyncIter(items)


class TestAzureEndToEnd:
    @pytest.fixture
    def client_with_fake(
        self,
    ) -> tuple[AzureStorageClient, _FakeContainerClient]:
        client = _real()
        fake = _FakeContainerClient("maisysstage", "data")
        client._container_client = fake  # type: ignore[assignment]
        return client, fake

    @pytest.mark.asyncio
    async def test_write_and_read(
        self,
        client_with_fake: tuple[AzureStorageClient, _FakeContainerClient],
    ) -> None:
        client, _ = client_with_fake
        info = await client.write_bytes(
            "f.txt", b"hello", content_type="text/plain", metadata={"k": "v"}
        )
        assert info.md5_hex == hashlib.md5(b"hello").hexdigest()
        assert info.metadata == {"k": "v"}
        assert await client.read_bytes("f.txt") == b"hello"

    @pytest.mark.asyncio
    async def test_read_missing_raises_object_not_found(
        self,
        client_with_fake: tuple[AzureStorageClient, _FakeContainerClient],
    ) -> None:
        client, _ = client_with_fake
        with pytest.raises(ObjectNotFoundException):
            await client.read_bytes("missing.txt")

    @pytest.mark.asyncio
    async def test_stat(
        self,
        client_with_fake: tuple[AzureStorageClient, _FakeContainerClient],
    ) -> None:
        client, _ = client_with_fake
        await client.write_bytes("s.txt", b"abcdef")
        info = await client.stat("s.txt")
        assert info.size_bytes == 6

    @pytest.mark.asyncio
    async def test_exists(
        self,
        client_with_fake: tuple[AzureStorageClient, _FakeContainerClient],
    ) -> None:
        client, _ = client_with_fake
        assert await client.exists("nope") is False
        await client.write_bytes("yep.txt", b"x")
        assert await client.exists("yep.txt") is True

    @pytest.mark.asyncio
    async def test_delete_missing_idempotent(
        self,
        client_with_fake: tuple[AzureStorageClient, _FakeContainerClient],
    ) -> None:
        client, _ = client_with_fake
        await client.delete("missing.txt")  # must not raise

    @pytest.mark.asyncio
    async def test_delete_existing(
        self,
        client_with_fake: tuple[AzureStorageClient, _FakeContainerClient],
    ) -> None:
        client, _ = client_with_fake
        await client.write_bytes("d.txt", b"x")
        await client.delete("d.txt")
        assert await client.exists("d.txt") is False

    @pytest.mark.asyncio
    async def test_list_prefix(
        self,
        client_with_fake: tuple[AzureStorageClient, _FakeContainerClient],
    ) -> None:
        client, _ = client_with_fake
        for i in range(3):
            await client.write_bytes(f"raw/{i}.txt", str(i).encode())
        await client.write_bytes("other/x.txt", b"x")
        infos = [b async for b in client.list_prefix("raw/")]
        assert len(infos) == 3
        assert all("raw/" in i.uri for i in infos)

    @pytest.mark.asyncio
    async def test_copy(
        self,
        client_with_fake: tuple[AzureStorageClient, _FakeContainerClient],
    ) -> None:
        client, _ = client_with_fake
        await client.write_bytes("src.txt", b"copy me")
        dst = await client.copy("src.txt", "dst.txt")
        assert dst.size_bytes == 7
        assert await client.read_bytes("dst.txt") == b"copy me"

    @pytest.mark.asyncio
    async def test_checksum_mismatch_raises(
        self,
        client_with_fake: tuple[AzureStorageClient, _FakeContainerClient],
    ) -> None:
        """Force the server-side md5 to disagree with the local one."""
        from shared.storage.exceptions import ChecksumMismatchException

        client, fake = client_with_fake

        # Replace get_blob_properties to return a wrong MD5.
        original_get_client = fake.get_blob_client

        def get_blob_client(name: str) -> _FakeBlobClient:
            bc = original_get_client(name)
            wrong_md5 = b"\x00" * 16

            async def liar() -> SimpleNamespace:
                return _props(size=5, md5_bytes=wrong_md5)

            bc.get_blob_properties = liar  # type: ignore[method-assign]
            return bc

        fake.get_blob_client = get_blob_client  # type: ignore[method-assign]
        with pytest.raises(ChecksumMismatchException):
            await client.write_bytes("x.txt", b"hello")

    @pytest.mark.asyncio
    async def test_close_releases_resources(self) -> None:
        """Close path: service.close() awaited, credential.close() awaited if present."""
        credential = MagicMock()
        credential.close = AsyncMock()
        client = AzureStorageClient(account="acct", container="c", credential=credential)
        client._service = MagicMock()
        client._service.close = AsyncMock()
        await client.close()
        client._service.close.assert_awaited_once()
        credential.close.assert_awaited_once()
