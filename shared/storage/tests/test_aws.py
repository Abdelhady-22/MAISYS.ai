"""Tests for the AWS S3 backend.

Two layers (same shape as test_gcs.py / test_azure.py):

1. **Protocol conformance** against :class:`FakeAWSStorageClient`. Includes
   a dedicated check that ``write_multipart`` produces a BlobInfo with
   ``md5_hex = None`` — modelling the S3 quirk where multipart objects
   have a hash-of-hashes ETag rather than a flat MD5.

2. **AWS-specific edge cases** on the real :class:`AWSStorageClient`:
   * ETag → md5_hex extraction (32-hex → MD5; dash → None; quoted /
     uppercase normalisation).
   * Exception translation for ClientError codes (NoSuchKey, AccessDenied,
     numeric 404/403, unknown).
   * URI scope validation.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from botocore.exceptions import ClientError

from shared.storage import (
    AWSStorageClient,
    AccessDeniedException,
    BlobInfo,
    ObjectNotFoundException,
    StorageException,
)
from shared.storage.aws import _etag_to_md5_hex
from shared.storage.tests.conftest import FakeAWSStorageClient


# ══════════════════════════════════════════════════════════════════════════
# Section 1 — Protocol conformance via FakeAWSStorageClient
# ══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def fake() -> FakeAWSStorageClient:
    return FakeAWSStorageClient(bucket="prod-bucket")


class TestProtocolConformanceAWS:
    @pytest.mark.asyncio
    async def test_read_after_write(self, fake: FakeAWSStorageClient) -> None:
        await fake.write_bytes("hello.txt", b"hello world")
        assert await fake.read_bytes("hello.txt") == b"hello world"

    @pytest.mark.asyncio
    async def test_write_returns_blobinfo_with_md5(self, fake: FakeAWSStorageClient) -> None:
        info = await fake.write_bytes("a.txt", b"abc")
        assert info.size_bytes == 3
        assert info.md5_hex == hashlib.md5(b"abc").hexdigest()
        assert info.uri == "s3://prod-bucket/a.txt"

    @pytest.mark.asyncio
    async def test_write_multipart_yields_no_md5(self, fake: FakeAWSStorageClient) -> None:
        """Hallmark S3 quirk — multipart-uploaded objects expose no flat MD5."""
        info = await fake.write_multipart("big.bin", b"some bytes")
        assert info.md5_hex is None
        assert info.size_bytes == len(b"some bytes")
        # stat() must mirror it.
        again = await fake.stat("big.bin")
        assert again.md5_hex is None

    @pytest.mark.asyncio
    async def test_write_records_content_type_and_metadata(
        self, fake: FakeAWSStorageClient
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
    async def test_exists(self, fake: FakeAWSStorageClient) -> None:
        assert await fake.exists("nope") is False
        await fake.write_bytes("present.txt", b"x")
        assert await fake.exists("present.txt") is True

    @pytest.mark.asyncio
    async def test_delete_is_idempotent(self, fake: FakeAWSStorageClient) -> None:
        await fake.write_bytes("d.txt", b"x")
        await fake.delete("d.txt")
        await fake.delete("d.txt")
        assert await fake.exists("d.txt") is False

    @pytest.mark.asyncio
    async def test_stat_returns_blobinfo(self, fake: FakeAWSStorageClient) -> None:
        await fake.write_bytes("s.txt", b"abcdef")
        info = await fake.stat("s.txt")
        assert isinstance(info, BlobInfo)
        assert info.size_bytes == 6
        assert info.md5_hex == hashlib.md5(b"abcdef").hexdigest()

    @pytest.mark.asyncio
    async def test_stat_missing_raises(self, fake: FakeAWSStorageClient) -> None:
        with pytest.raises(ObjectNotFoundException):
            await fake.stat("nope")

    @pytest.mark.asyncio
    async def test_read_missing_raises(self, fake: FakeAWSStorageClient) -> None:
        with pytest.raises(ObjectNotFoundException):
            await fake.read_bytes("nope")

    @pytest.mark.asyncio
    async def test_copy_preserves_md5(self, fake: FakeAWSStorageClient) -> None:
        await fake.write_bytes("src.txt", b"copy me please")
        src_info = await fake.stat("src.txt")
        dst_info = await fake.copy("src.txt", "dst.txt")
        assert dst_info.size_bytes == src_info.size_bytes
        assert dst_info.md5_hex == src_info.md5_hex
        assert await fake.read_bytes("dst.txt") == b"copy me please"

    @pytest.mark.asyncio
    async def test_copy_of_multipart_keeps_no_md5(self, fake: FakeAWSStorageClient) -> None:
        """Copying a multipart object preserves the absence of a flat MD5."""
        await fake.write_multipart("big.bin", b"some bytes")
        copied = await fake.copy("big.bin", "big-copy.bin")
        assert copied.md5_hex is None

    @pytest.mark.asyncio
    async def test_copy_missing_raises(self, fake: FakeAWSStorageClient) -> None:
        with pytest.raises(ObjectNotFoundException):
            await fake.copy("nope", "anywhere")

    @pytest.mark.asyncio
    async def test_list_prefix_iterates(self, fake: FakeAWSStorageClient) -> None:
        for i in range(5):
            await fake.write_bytes(f"raw/file-{i}.txt", f"data{i}".encode())
        await fake.write_bytes("other/x.txt", b"x")
        found = [info.uri async for info in fake.list_prefix("raw/")]
        assert len(found) == 5
        assert all(u.startswith("s3://prod-bucket/raw/") for u in found)

    @pytest.mark.asyncio
    async def test_signed_url_nonempty(self, fake: FakeAWSStorageClient) -> None:
        await fake.write_bytes("x.txt", b"x")
        url = await fake.signed_url("x.txt", expires_in=timedelta(minutes=5))
        assert url and url.startswith("s3://prod-bucket/x.txt")

    @pytest.mark.asyncio
    async def test_uri_path_accepted(self, fake: FakeAWSStorageClient) -> None:
        await fake.write_bytes("s3://prod-bucket/u.txt", b"u")
        assert await fake.read_bytes("u.txt") == b"u"
        assert await fake.read_bytes("s3://prod-bucket/u.txt") == b"u"

    @pytest.mark.asyncio
    async def test_uri_wrong_bucket_rejected(self, fake: FakeAWSStorageClient) -> None:
        with pytest.raises(ValueError, match="does not match"):
            await fake.read_bytes("s3://wrong-bucket/x.txt")

    @pytest.mark.asyncio
    async def test_access_denied_surfaces(self, fake: FakeAWSStorageClient) -> None:
        fake.deny_access_to("secret.txt")
        with pytest.raises(AccessDeniedException):
            await fake.read_bytes("secret.txt")


# ══════════════════════════════════════════════════════════════════════════
# Section 2 — AWS-specific edge cases (real AWSStorageClient)
# ══════════════════════════════════════════════════════════════════════════
class TestEtagToMd5Hex:
    """ETag handling is the single most important AWS quirk to get right."""

    def test_plain_md5_etag_extracts(self) -> None:
        digest = hashlib.md5(b"hello").hexdigest()  # 32 hex chars
        assert _etag_to_md5_hex(digest) == digest

    def test_quoted_etag_stripped(self) -> None:
        digest = hashlib.md5(b"hello").hexdigest()
        assert _etag_to_md5_hex(f'"{digest}"') == digest

    def test_uppercase_normalized(self) -> None:
        digest = hashlib.md5(b"hello").hexdigest()
        assert _etag_to_md5_hex(digest.upper()) == digest

    def test_multipart_etag_returns_none(self) -> None:
        # Multipart hash-of-hashes ETag — has a dash, NOT an MD5.
        multipart_etag = '"9bb58f26192e4ba00f01e2e7b136bbd8-5"'
        assert _etag_to_md5_hex(multipart_etag) is None

    def test_none_returns_none(self) -> None:
        assert _etag_to_md5_hex(None) is None

    def test_garbage_returns_none(self) -> None:
        assert _etag_to_md5_hex("not-an-etag") is None
        assert _etag_to_md5_hex("") is None

    def test_wrong_length_returns_none(self) -> None:
        # 30 hex chars — close, but not an MD5.
        assert _etag_to_md5_hex("a" * 30) is None


def _client_error(code: str, status: int) -> ClientError:
    """Build a botocore ClientError with the given code + status."""
    return ClientError(
        error_response={
            "Error": {"Code": code, "Message": "synthetic"},
            "ResponseMetadata": {
                "HTTPStatusCode": status,
                "HTTPHeaders": {},
                "HostId": "synthetic-host",
                "RequestId": "synthetic-request",
                "RetryAttempts": 0,
            },
        },
        operation_name="TestOp",
    )


class TestExceptionTranslation:
    @pytest.mark.parametrize(
        "code, status, expected_cls",
        [
            ("NoSuchKey", 404, ObjectNotFoundException),
            ("404", 404, ObjectNotFoundException),
            ("NotFound", 404, ObjectNotFoundException),
            ("AccessDenied", 403, AccessDeniedException),
            ("403", 403, AccessDeniedException),
        ],
    )
    def test_translate_known_codes(
        self, code: str, status: int, expected_cls: type[StorageException]
    ) -> None:
        exc = _client_error(code, status)
        translated = AWSStorageClient._translate("key", exc)
        assert isinstance(translated, expected_cls)
        assert translated.cause is exc

    def test_translate_unknown_falls_back_to_storage_exception(self) -> None:
        exc = _client_error("InternalError", 500)
        translated = AWSStorageClient._translate("key", exc)
        assert isinstance(translated, StorageException)
        # MUST NOT be one of the more specific subclasses.
        assert not isinstance(translated, (ObjectNotFoundException, AccessDeniedException))

    def test_translate_non_client_error(self) -> None:
        exc = RuntimeError("network down")
        translated = AWSStorageClient._translate("key", exc)
        assert isinstance(translated, StorageException)
        assert translated.cause is exc


class TestUriResolution:
    def _client(self) -> AWSStorageClient:
        return AWSStorageClient(
            bucket="mybucket",
            session=MagicMock(name="stub-session"),
        )

    def test_bare_path(self) -> None:
        assert self._client()._resolve_path("foo/bar.txt") == "foo/bar.txt"

    def test_full_uri(self) -> None:
        assert self._client()._resolve_path("s3://mybucket/foo/bar.txt") == "foo/bar.txt"

    def test_wrong_bucket_rejected(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            self._client()._resolve_path("s3://other-bucket/x.txt")

    def test_leading_slash_stripped(self) -> None:
        assert self._client()._resolve_path("/foo/bar.txt") == "foo/bar.txt"


# ──────────────────────────────────────────────────────────────────────────
# End-to-end-ish: write_bytes through a mocked aioboto3 session
# ──────────────────────────────────────────────────────────────────────────
class _AsyncCtx:
    """Mimics an aioboto3 async-context-manager client."""

    def __init__(self, client: Any) -> None:
        self._client = client

    async def __aenter__(self) -> Any:
        return self._client

    async def __aexit__(self, *_: Any) -> None:
        return None


def _mock_session(s3_client: Any) -> Any:
    sess = MagicMock(name="aioboto3.Session")
    sess.client.return_value = _AsyncCtx(s3_client)
    return sess


class TestWriteBytesEndToEnd:
    @pytest.mark.asyncio
    async def test_write_bytes_verifies_md5_against_etag(self) -> None:
        """Real AWSStorageClient.write_bytes computes MD5, expects ETag agreement."""
        data = b"hello world"
        local_md5 = hashlib.md5(data).hexdigest()
        s3 = MagicMock(name="s3-client")
        s3.put_object = AsyncMock(return_value={})
        s3.head_object = AsyncMock(
            return_value={
                "ContentLength": len(data),
                "ETag": f'"{local_md5}"',
                "ContentType": "text/plain",
                "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "Metadata": {"k": "v"},
            }
        )
        client = AWSStorageClient(bucket="mybucket", session=_mock_session(s3))
        info = await client.write_bytes(
            "hello.txt", data, content_type="text/plain", metadata={"k": "v"}
        )
        assert info.uri == "s3://mybucket/hello.txt"
        assert info.size_bytes == len(data)
        assert info.md5_hex == local_md5
        assert info.metadata == {"k": "v"}
        s3.put_object.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_write_bytes_raises_on_md5_mismatch(self) -> None:
        from shared.storage.exceptions import ChecksumMismatchException

        s3 = MagicMock()
        s3.put_object = AsyncMock(return_value={})
        # Server reports a DIFFERENT MD5 → ChecksumMismatchException.
        wrong_md5 = "0" * 32
        s3.head_object = AsyncMock(
            return_value={
                "ContentLength": 5,
                "ETag": f'"{wrong_md5}"',
                "ContentType": None,
                "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "Metadata": {},
            }
        )
        client = AWSStorageClient(bucket="b", session=_mock_session(s3))
        with pytest.raises(ChecksumMismatchException):
            await client.write_bytes("x.txt", b"hello")

    @pytest.mark.asyncio
    async def test_exists_false_on_404(self) -> None:
        s3 = MagicMock()
        s3.head_object = AsyncMock(side_effect=_client_error("404", 404))
        client = AWSStorageClient(bucket="b", session=_mock_session(s3))
        assert await client.exists("missing.txt") is False

    @pytest.mark.asyncio
    async def test_exists_raises_on_other_error(self) -> None:
        s3 = MagicMock()
        s3.head_object = AsyncMock(side_effect=_client_error("AccessDenied", 403))
        client = AWSStorageClient(bucket="b", session=_mock_session(s3))
        with pytest.raises(AccessDeniedException):
            await client.exists("nope.txt")

    @pytest.mark.asyncio
    async def test_signed_url_invokes_presigner(self) -> None:
        s3 = MagicMock()
        s3.generate_presigned_url = AsyncMock(
            return_value="https://signed.example/file?X-Amz-Sig=fake"
        )
        client = AWSStorageClient(bucket="b", session=_mock_session(s3))
        url = await client.signed_url("file.txt", timedelta(minutes=15))
        assert url.startswith("https://signed.example/file")
        s3.generate_presigned_url.assert_awaited_once()
        call = s3.generate_presigned_url.call_args
        assert call.kwargs["ClientMethod"] == "get_object"
        assert call.kwargs["Params"] == {"Bucket": "b", "Key": "file.txt"}
        assert call.kwargs["ExpiresIn"] == 15 * 60

    @pytest.mark.asyncio
    async def test_signed_url_invalid_method(self) -> None:
        client = AWSStorageClient(bucket="b", session=_mock_session(MagicMock()))
        with pytest.raises(ValueError, match="GET or PUT"):
            await client.signed_url("x.txt", timedelta(minutes=5), method="DELETE")

    @pytest.mark.asyncio
    async def test_list_prefix_paginates(self) -> None:
        s3 = MagicMock()

        class _Paginator:
            def paginate(self, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
                async def _gen() -> AsyncIterator[dict[str, Any]]:
                    yield {
                        "Contents": [
                            {
                                "Key": "raw/a.txt",
                                "Size": 5,
                                "ETag": '"d41d8cd98f00b204e9800998ecf8427e"',
                                "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc),
                            }
                        ]
                    }
                    yield {
                        "Contents": [
                            {
                                "Key": "raw/b.txt",
                                "Size": 9,
                                "ETag": '"abc123-2"',  # multipart
                                "LastModified": datetime(2026, 1, 2, tzinfo=timezone.utc),
                            }
                        ]
                    }

                return _gen()

        s3.get_paginator = MagicMock(return_value=_Paginator())
        client = AWSStorageClient(bucket="b", session=_mock_session(s3))
        items = [info async for info in client.list_prefix("raw/")]
        assert [i.uri for i in items] == ["s3://b/raw/a.txt", "s3://b/raw/b.txt"]
        # Second item is multipart → no md5_hex.
        assert items[0].md5_hex == "d41d8cd98f00b204e9800998ecf8427e"
        assert items[1].md5_hex is None

    @pytest.mark.asyncio
    async def test_read_bytes(self) -> None:
        class _Body:
            async def __aenter__(self) -> "_Body":
                return self

            async def __aexit__(self, *_: Any) -> None:
                return None

            async def read(self) -> bytes:
                return b"payload"

        s3 = MagicMock()
        s3.get_object = AsyncMock(return_value={"Body": _Body()})
        client = AWSStorageClient(bucket="b", session=_mock_session(s3))
        data = await client.read_bytes("file.txt")
        assert data == b"payload"
        s3.get_object.assert_awaited_once_with(Bucket="b", Key="file.txt")

    @pytest.mark.asyncio
    async def test_read_bytes_missing_raises(self) -> None:
        s3 = MagicMock()
        s3.get_object = AsyncMock(side_effect=_client_error("NoSuchKey", 404))
        client = AWSStorageClient(bucket="b", session=_mock_session(s3))
        with pytest.raises(ObjectNotFoundException):
            await client.read_bytes("missing.txt")

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        s3 = MagicMock()
        s3.delete_object = AsyncMock(return_value={})
        client = AWSStorageClient(bucket="b", session=_mock_session(s3))
        await client.delete("file.txt")
        s3.delete_object.assert_awaited_once_with(Bucket="b", Key="file.txt")

    @pytest.mark.asyncio
    async def test_delete_translates_error(self) -> None:
        s3 = MagicMock()
        s3.delete_object = AsyncMock(side_effect=_client_error("AccessDenied", 403))
        client = AWSStorageClient(bucket="b", session=_mock_session(s3))
        with pytest.raises(AccessDeniedException):
            await client.delete("file.txt")

    @pytest.mark.asyncio
    async def test_stat(self) -> None:
        digest = hashlib.md5(b"abc").hexdigest()
        s3 = MagicMock()
        s3.head_object = AsyncMock(
            return_value={
                "ContentLength": 3,
                "ETag": f'"{digest}"',
                "ContentType": "text/plain",
                "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "Metadata": {},
            }
        )
        client = AWSStorageClient(bucket="b", session=_mock_session(s3))
        info = await client.stat("x.txt")
        assert info.size_bytes == 3
        assert info.md5_hex == digest

    @pytest.mark.asyncio
    async def test_copy(self) -> None:
        digest = hashlib.md5(b"copied").hexdigest()
        s3 = MagicMock()
        s3.copy_object = AsyncMock(return_value={})
        s3.head_object = AsyncMock(
            return_value={
                "ContentLength": 6,
                "ETag": f'"{digest}"',
                "ContentType": None,
                "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc),
                "Metadata": {},
            }
        )
        client = AWSStorageClient(bucket="b", session=_mock_session(s3))
        info = await client.copy("src.txt", "dst.txt")
        assert info.uri == "s3://b/dst.txt"
        s3.copy_object.assert_awaited_once_with(
            Bucket="b",
            Key="dst.txt",
            CopySource={"Bucket": "b", "Key": "src.txt"},
        )
