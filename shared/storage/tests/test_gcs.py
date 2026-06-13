"""Tests for the GCS backend.

Two layers:

1. **Protocol conformance** against :class:`FakeGCSStorageClient` (in
   :mod:`conftest`). These exercise the StorageClient API semantics
   without involving the google-cloud-storage SDK at all.

2. **Edge cases on the real** :class:`GCSStorageClient` — narrow tests
   that drive the translation logic (MD5 base64 → hex, URI parsing,
   exception translation) by injecting a small in-memory fake of the
   GCS SDK Client / Bucket / Blob, mirroring the FakeClient pattern in
   ``data-pipeline/cloud/test_upload_local_to_gcs.py``.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest
from google.api_core import exceptions as gcs_exceptions

from shared.storage import (
    AccessDeniedException,
    BlobInfo,
    GCSStorageClient,
    ObjectNotFoundException,
    StorageException,
)
from shared.storage.gcs import _md5_b64_to_hex
from shared.storage.tests.conftest import FakeGCSStorageClient


# ══════════════════════════════════════════════════════════════════════════
# Section 1 — Protocol conformance via FakeGCSStorageClient
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def fake() -> FakeGCSStorageClient:
    return FakeGCSStorageClient(bucket="test-bucket")


class TestProtocolConformanceGCS:
    """Same test cases run against every backend's fake (this file's copy)."""

    @pytest.mark.asyncio
    async def test_read_after_write(self, fake: FakeGCSStorageClient) -> None:
        await fake.write_bytes("hello.txt", b"hello world")
        assert await fake.read_bytes("hello.txt") == b"hello world"

    @pytest.mark.asyncio
    async def test_write_returns_blobinfo_with_md5(self, fake: FakeGCSStorageClient) -> None:
        info = await fake.write_bytes("a.txt", b"abc")
        assert info.size_bytes == 3
        assert info.md5_hex == hashlib.md5(b"abc").hexdigest()
        assert info.uri == "gs://test-bucket/a.txt"

    @pytest.mark.asyncio
    async def test_write_records_content_type_and_metadata(
        self, fake: FakeGCSStorageClient
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
    async def test_exists(self, fake: FakeGCSStorageClient) -> None:
        assert await fake.exists("nope") is False
        await fake.write_bytes("present.txt", b"x")
        assert await fake.exists("present.txt") is True

    @pytest.mark.asyncio
    async def test_delete_is_idempotent(self, fake: FakeGCSStorageClient) -> None:
        await fake.write_bytes("d.txt", b"x")
        await fake.delete("d.txt")
        # Second delete must not raise.
        await fake.delete("d.txt")
        assert await fake.exists("d.txt") is False

    @pytest.mark.asyncio
    async def test_stat_returns_blobinfo(self, fake: FakeGCSStorageClient) -> None:
        await fake.write_bytes("s.txt", b"abcdef")
        info = await fake.stat("s.txt")
        assert isinstance(info, BlobInfo)
        assert info.size_bytes == 6
        assert info.md5_hex == hashlib.md5(b"abcdef").hexdigest()

    @pytest.mark.asyncio
    async def test_stat_missing_raises(self, fake: FakeGCSStorageClient) -> None:
        with pytest.raises(ObjectNotFoundException):
            await fake.stat("nope")

    @pytest.mark.asyncio
    async def test_read_missing_raises(self, fake: FakeGCSStorageClient) -> None:
        with pytest.raises(ObjectNotFoundException):
            await fake.read_bytes("nope")

    @pytest.mark.asyncio
    async def test_copy_preserves_md5(self, fake: FakeGCSStorageClient) -> None:
        await fake.write_bytes("src.txt", b"copy me please")
        src_info = await fake.stat("src.txt")
        dst_info = await fake.copy("src.txt", "dst.txt")
        assert dst_info.size_bytes == src_info.size_bytes
        assert dst_info.md5_hex == src_info.md5_hex
        assert await fake.read_bytes("dst.txt") == b"copy me please"

    @pytest.mark.asyncio
    async def test_copy_missing_raises(self, fake: FakeGCSStorageClient) -> None:
        with pytest.raises(ObjectNotFoundException):
            await fake.copy("nope", "anywhere")

    @pytest.mark.asyncio
    async def test_list_prefix_paginates_via_async_iter(self, fake: FakeGCSStorageClient) -> None:
        for i in range(5):
            await fake.write_bytes(f"raw/file-{i}.txt", f"data{i}".encode())
        await fake.write_bytes("other/x.txt", b"x")
        found = [info.uri async for info in fake.list_prefix("raw/")]
        assert len(found) == 5
        assert all(u.startswith("gs://test-bucket/raw/") for u in found)

    @pytest.mark.asyncio
    async def test_list_prefix_empty(self, fake: FakeGCSStorageClient) -> None:
        found = [info async for info in fake.list_prefix("none/")]
        assert found == []

    @pytest.mark.asyncio
    async def test_signed_url_nonempty(self, fake: FakeGCSStorageClient) -> None:
        await fake.write_bytes("x.txt", b"x")
        url = await fake.signed_url("x.txt", expires_in=timedelta(minutes=5))
        assert url and url.startswith("gs://test-bucket/x.txt")

    @pytest.mark.asyncio
    async def test_uri_path_accepted(self, fake: FakeGCSStorageClient) -> None:
        await fake.write_bytes("gs://test-bucket/u.txt", b"u")
        assert await fake.read_bytes("u.txt") == b"u"
        assert await fake.read_bytes("gs://test-bucket/u.txt") == b"u"

    @pytest.mark.asyncio
    async def test_uri_wrong_bucket_rejected(self, fake: FakeGCSStorageClient) -> None:
        with pytest.raises(ValueError, match="does not match"):
            await fake.read_bytes("gs://wrong-bucket/x.txt")

    @pytest.mark.asyncio
    async def test_access_denied_surfaces(self, fake: FakeGCSStorageClient) -> None:
        fake.deny_access_to("secret.txt")
        with pytest.raises(AccessDeniedException):
            await fake.read_bytes("secret.txt")
        # exists() must also raise, not silently False.
        with pytest.raises(AccessDeniedException):
            await fake.exists("secret.txt")


# ══════════════════════════════════════════════════════════════════════════
# Section 2 — GCS-specific edge cases (real GCSStorageClient + SDK fakes)
# ══════════════════════════════════════════════════════════════════════════
class TestMd5Base64ToHex:
    """The GCS SDK exposes md5_hash as base64 — must convert to lowercase hex."""

    def test_valid_b64_round_trips_to_hex(self) -> None:
        raw = hashlib.md5(b"hello").digest()  # 16 bytes
        b64 = base64.b64encode(raw).decode("ascii")
        assert _md5_b64_to_hex(b64) == raw.hex()

    def test_none_passes_through(self) -> None:
        assert _md5_b64_to_hex(None) is None

    def test_invalid_b64_returns_none(self) -> None:
        assert _md5_b64_to_hex("not-base64!!") is None

    def test_wrong_length_returns_none(self) -> None:
        # 10 random bytes → not a 16-byte digest.
        short = base64.b64encode(b"0123456789").decode("ascii")
        assert _md5_b64_to_hex(short) is None


# A small in-memory fake of the google-cloud-storage SDK that GCSStorageClient
# accepts via its `client` constructor kwarg. Mirrors the FakeBucket / FakeBlob
# / FakeClient triplet from upload_local_to_gcs.py.
def _b64_md5(data: bytes) -> str:
    return base64.b64encode(hashlib.md5(data).digest()).decode("ascii")


class _FakeSdkBlob:
    def __init__(self, bucket: "_FakeSdkBucket", name: str) -> None:
        self._bucket = bucket
        self.name = name
        self.metadata: dict[str, str] | None = None
        self.content_type: str | None = None
        self.size: int = 0
        self.updated: datetime = datetime.now(timezone.utc)
        self.time_created: datetime = self.updated
        self.md5_hash: str | None = None

    def reload(self, client: Any | None = None) -> None:
        if self.name not in self._bucket.store:
            raise gcs_exceptions.NotFound(self.name)  # type: ignore[no-untyped-call]
        data = self._bucket.store[self.name]
        self.size = len(data)
        self.md5_hash = _b64_md5(data)

    def exists(self, client: Any | None = None) -> bool:
        return self.name in self._bucket.store

    def download_as_bytes(self, client: Any | None = None) -> bytes:
        if self.name not in self._bucket.store:
            raise gcs_exceptions.NotFound(self.name)  # type: ignore[no-untyped-call]
        return self._bucket.store[self.name]

    def upload_from_string(
        self,
        data: bytes | str,
        content_type: str | None = None,
        client: Any | None = None,
    ) -> None:
        payload = data.encode("utf-8") if isinstance(data, str) else data
        self._bucket.store[self.name] = payload
        self.content_type = content_type

    def delete(self, client: Any | None = None) -> None:
        if self.name not in self._bucket.store:
            raise gcs_exceptions.NotFound(self.name)  # type: ignore[no-untyped-call]
        del self._bucket.store[self.name]

    def generate_signed_url(
        self,
        version: str = "v4",
        expiration: Any = None,
        method: str = "GET",
    ) -> str:
        return f"https://signed.example/{self._bucket.name}/{self.name}?m={method}"


class _FakeSdkBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self.store: dict[str, bytes] = {}

    def blob(self, name: str) -> _FakeSdkBlob:
        return _FakeSdkBlob(self, name)

    def copy_blob(
        self,
        src: _FakeSdkBlob,
        dst_bucket: "_FakeSdkBucket",
        new_name: str,
        client: Any | None = None,
    ) -> _FakeSdkBlob:
        if src.name not in self.store:
            raise gcs_exceptions.NotFound(src.name)  # type: ignore[no-untyped-call]
        dst_bucket.store[new_name] = self.store[src.name]
        return dst_bucket.blob(new_name)


class _FakeSdkClient:
    def __init__(self) -> None:
        self.buckets: dict[str, _FakeSdkBucket] = {}

    def bucket(self, name: str) -> _FakeSdkBucket:
        return self.buckets.setdefault(name, _FakeSdkBucket(name))

    def list_blobs(
        self,
        bucket_name: str,
        prefix: str = "",
        page_token: Any = None,
        max_results: int | None = None,
    ) -> Any:
        bucket = self.buckets.setdefault(bucket_name, _FakeSdkBucket(bucket_name))
        matching = sorted(k for k in bucket.store if k.startswith(prefix))
        blobs = []
        for name in matching:
            blob = bucket.blob(name)
            blob.reload()
            blobs.append(blob)
        # The real iterator exposes .pages and .next_page_token; our fake
        # returns everything in a single page (simpler — pagination
        # semantics are covered by the protocol conformance tests via
        # FakeGCSStorageClient).
        iterator = MagicMock()
        iterator.pages = iter([blobs])
        iterator.next_page_token = None
        return iterator


@pytest.fixture
def real_with_fake_sdk() -> tuple[GCSStorageClient, _FakeSdkClient]:
    sdk = _FakeSdkClient()
    return GCSStorageClient(bucket="mybucket", client=sdk), sdk


class TestRealGCSClientWithFakeSdk:
    """Drive the real GCSStorageClient through a mocked SDK to exercise its
    translation logic — MD5 conversion, exception mapping, BlobInfo build."""

    @pytest.mark.asyncio
    async def test_md5_conversion_end_to_end(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        info = await client.write_bytes("a.txt", b"hello")
        # The MD5 surfaced by GCSStorageClient must be lowercase hex, not b64.
        assert info.md5_hex == hashlib.md5(b"hello").hexdigest()

    @pytest.mark.asyncio
    async def test_read_after_write(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        await client.write_bytes("a.txt", b"hello")
        assert await client.read_bytes("a.txt") == b"hello"

    @pytest.mark.asyncio
    async def test_read_missing_raises_object_not_found(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        with pytest.raises(ObjectNotFoundException):
            await client.read_bytes("absent.txt")

    @pytest.mark.asyncio
    async def test_forbidden_translates_to_access_denied(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk

        def raising_blob(name: str) -> _FakeSdkBlob:
            raise gcs_exceptions.Forbidden(f"403 on {name}")  # type: ignore[no-untyped-call]

        # Patch the bucket the client is actually holding, not a different
        # one in the registry — client._bucket was captured at construction.
        client._bucket.blob = raising_blob
        with pytest.raises(AccessDeniedException):
            await client.read_bytes("secret.txt")

    @pytest.mark.asyncio
    async def test_uri_path_resolves(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        await client.write_bytes("gs://mybucket/x.txt", b"x")
        assert await client.exists("x.txt") is True
        assert await client.exists("gs://mybucket/x.txt") is True

    @pytest.mark.asyncio
    async def test_uri_wrong_bucket_rejected(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        with pytest.raises(ValueError, match="does not match"):
            await client.read_bytes("gs://other/x.txt")

    @pytest.mark.asyncio
    async def test_delete_missing_is_idempotent(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        # Should NOT raise even though the blob doesn't exist.
        await client.delete("nope.txt")

    @pytest.mark.asyncio
    async def test_copy_returns_blob_info(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        await client.write_bytes("src.txt", b"contents")
        info = await client.copy("src.txt", "dst.txt")
        assert info.uri == "gs://mybucket/dst.txt"
        assert info.size_bytes == 8
        assert info.md5_hex == hashlib.md5(b"contents").hexdigest()

    @pytest.mark.asyncio
    async def test_signed_url_get(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        url = await client.signed_url("x.txt", timedelta(minutes=10))
        assert url.startswith("https://signed.example/mybucket/x.txt")

    @pytest.mark.asyncio
    async def test_signed_url_invalid_method(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        with pytest.raises(ValueError, match="Unsupported signed_url method"):
            await client.signed_url("x.txt", timedelta(minutes=10), method="OPTIONS")

    @pytest.mark.asyncio
    async def test_unexpected_sdk_error_translates_to_storage_exception(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk

        def raising_blob(name: str) -> _FakeSdkBlob:
            raise gcs_exceptions.GoogleAPICallError("transient")  # type: ignore[no-untyped-call]

        client._bucket.blob = raising_blob
        with pytest.raises(StorageException):
            await client.read_bytes("x.txt")

    @pytest.mark.asyncio
    async def test_list_prefix_iterates(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        for i in range(3):
            await client.write_bytes(f"raw/{i}.txt", str(i).encode())
        infos = [b async for b in client.list_prefix("raw/")]
        assert {b.uri for b in infos} == {f"gs://mybucket/raw/{i}.txt" for i in range(3)}

    @pytest.mark.asyncio
    async def test_list_prefix_full_uri_resolves(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        await client.write_bytes("raw/a.txt", b"a")
        infos = [b async for b in client.list_prefix("gs://mybucket/raw/")]
        assert {b.uri for b in infos} == {"gs://mybucket/raw/a.txt"}

    @pytest.mark.asyncio
    async def test_list_prefix_wrong_bucket_uri_rejected(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        with pytest.raises(ValueError, match="does not match"):
            async for _ in client.list_prefix("gs://other/raw/"):
                pass

    @pytest.mark.asyncio
    async def test_checksum_mismatch_raises(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        """If GCS reports a different MD5 than we computed locally, fail loudly."""
        from shared.storage.exceptions import ChecksumMismatchException

        client, _ = real_with_fake_sdk

        # Wrap the fake blob's reload() so md5_hash reports a different digest.
        original_blob = client._bucket.blob

        def patched_blob(name: str) -> _FakeSdkBlob:
            b: _FakeSdkBlob = original_blob(name)
            real_reload = b.reload

            def lying_reload(client: Any | None = None) -> None:
                real_reload(client=client)
                b.md5_hash = base64.b64encode(b"\x00" * 16).decode("ascii")

            b.reload = lying_reload  # type: ignore[method-assign]
            return b

        client._bucket.blob = patched_blob
        with pytest.raises(ChecksumMismatchException):
            await client.write_bytes("x.txt", b"hello")

    @pytest.mark.asyncio
    async def test_stat_translates_not_found(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        with pytest.raises(ObjectNotFoundException):
            await client.stat("missing.txt")

    @pytest.mark.asyncio
    async def test_exists_true_after_write(
        self, real_with_fake_sdk: tuple[GCSStorageClient, _FakeSdkClient]
    ) -> None:
        client, _ = real_with_fake_sdk
        assert await client.exists("nope.txt") is False
        await client.write_bytes("yes.txt", b"x")
        assert await client.exists("yes.txt") is True
