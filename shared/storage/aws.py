"""AWS S3 backend implementation of StorageClient.

Wraps ``aioboto3`` (native async). Auth uses the standard boto3 credential
chain: environment variables, ~/.aws/credentials, IAM role (instance
profile, ECS task role, or EKS IRSA via web-identity token).

ETag handling
-------------
S3 ETags are not always MD5 hashes. The convention this adapter follows:

* If the ETag (stripped of surrounding quotes) is 32 hex chars: it IS the
  MD5 of the object. Surface it as ``md5_hex``.
* If the ETag contains a hyphen (e.g. ``"<md5>-<parts>"``): the object
  was multipart-uploaded. The hash is a hash-of-hashes and cannot be
  compared against a flat MD5 of the source bytes. Surface
  ``md5_hex = None`` — downstream verifiers (e.g. verify_checksums.py)
  reconstruct the multipart hash separately when they need to.
"""

from __future__ import annotations

import hashlib
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Final
from urllib.parse import urlparse

import aioboto3
from botocore.exceptions import ClientError

from shared.logger import get_logger
from shared.storage.exceptions import (
    AccessDeniedException,
    ChecksumMismatchException,
    ObjectNotFoundException,
    StorageException,
)
from shared.storage.types import BlobInfo

logger = get_logger(__name__)

STREAMING_THRESHOLD_BYTES: Final[int] = 100 * 1024 * 1024  # 100 MB

# Plain MD5 ETag (32 hex chars, optionally quoted). Multipart ETags have a
# dash separating the hash-of-hashes from the part count, e.g.
# "9bb58f26..."  → single-part
# "9bb58f26...-5" → multipart, 5 parts
_PLAIN_MD5_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{32}$")


def _etag_to_md5_hex(etag: str | None) -> str | None:
    """Extract a plain MD5 from an ETag if possible. Multipart → None."""
    if etag is None:
        return None
    stripped = etag.strip().strip('"').lower()
    if "-" in stripped:
        return None
    return stripped if _PLAIN_MD5_RE.match(stripped) else None


class AWSStorageClient:
    """StorageClient implementation backed by AWS S3 (via aioboto3)."""

    def __init__(
        self,
        bucket: str,
        *,
        region: str | None = None,
        session: aioboto3.Session | None = None,
    ) -> None:
        """Construct an S3-backed StorageClient.

        Args:
            bucket: S3 bucket name.
            region: Optional AWS region. If None, falls back to the
                session/environment default.
            session: Optional pre-built ``aioboto3.Session``. Useful in
                tests to inject a session backed by mocked credentials.
        """
        self._bucket = bucket
        self._region = region
        self._session = session if session is not None else aioboto3.Session()

    # ──────────────────────────────────────────────────────────────────
    # Path resolution
    # ──────────────────────────────────────────────────────────────────
    def _resolve_path(self, path: str) -> str:
        if path.startswith("s3://"):
            parsed = urlparse(path)
            if parsed.netloc != self._bucket:
                raise ValueError(
                    f"URI bucket {parsed.netloc!r} does not match this client's "
                    f"bucket {self._bucket!r}"
                )
            return parsed.path.lstrip("/")
        return path.lstrip("/")

    def _uri(self, key: str) -> str:
        return f"s3://{self._bucket}/{key}"

    # ──────────────────────────────────────────────────────────────────
    # SDK exception translation
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _translate(path: str, exc: BaseException) -> StorageException:
        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"NoSuchKey", "404", "NotFound"} or status == 404:
                return ObjectNotFoundException(
                    f"Object not found: {path}",
                    details={"path": path, "aws_code": code},
                    cause=exc,
                )
            if code in {"AccessDenied", "403"} or status == 403:
                return AccessDeniedException(
                    f"Access denied to {path}",
                    details={"path": path, "aws_code": code},
                    cause=exc,
                )
        return StorageException(
            f"S3 error on {path}: {exc}",
            details={"path": path, "exception_type": type(exc).__name__},
            cause=exc,
        )

    # ──────────────────────────────────────────────────────────────────
    # Client context — every public method uses this so the SDK client is
    # always cleaned up correctly. aioboto3 clients are async context
    # managers; sharing one across calls leaks resources.
    # ──────────────────────────────────────────────────────────────────
    @asynccontextmanager
    async def _s3(self) -> AsyncIterator[Any]:
        async with self._session.client("s3", region_name=self._region) as client:
            yield client

    # ──────────────────────────────────────────────────────────────────
    # BlobInfo construction from a head_object response
    # ──────────────────────────────────────────────────────────────────
    def _info_from_head(self, key: str, head: dict[str, Any]) -> BlobInfo:
        last_modified = head.get("LastModified") or datetime.now(timezone.utc)
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        metadata = dict(head.get("Metadata") or {})
        return BlobInfo(
            uri=self._uri(key),
            size_bytes=int(head.get("ContentLength") or 0),
            md5_hex=_etag_to_md5_hex(head.get("ETag")),
            content_type=head.get("ContentType"),
            last_modified=last_modified,
            metadata=metadata,
        )

    # ──────────────────────────────────────────────────────────────────
    # Read / Write
    # ──────────────────────────────────────────────────────────────────
    async def read_bytes(self, path: str) -> bytes:
        key = self._resolve_path(path)
        try:
            async with self._s3() as s3:
                obj = await s3.get_object(Bucket=self._bucket, Key=key)
                async with obj["Body"] as stream:
                    data = await stream.read()
        except ClientError as exc:
            raise self._translate(key, exc) from exc
        size = len(data)
        logger.info(
            "aws.read",
            key=key,
            size_bytes=size,
            mode="streaming" if size >= STREAMING_THRESHOLD_BYTES else "single",
        )
        return bytes(data)

    async def write_bytes(
        self,
        path: str,
        data: bytes,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> BlobInfo:
        key = self._resolve_path(path)
        local_md5 = hashlib.md5(data).hexdigest()
        put_kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": data,
        }
        if content_type is not None:
            put_kwargs["ContentType"] = content_type
        if metadata:
            put_kwargs["Metadata"] = metadata

        try:
            async with self._s3() as s3:
                await s3.put_object(**put_kwargs)
                head = await s3.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise self._translate(key, exc) from exc

        info = self._info_from_head(key, head)
        # Single put_object always produces a plain MD5 ETag; verify it
        # matches what we sent. Multipart (md5_hex=None) won't reach here
        # because put_object doesn't do multipart.
        if info.md5_hex is not None and info.md5_hex != local_md5:
            raise ChecksumMismatchException(
                f"MD5 mismatch on write to {key}: " f"local={local_md5}, server={info.md5_hex}",
                details={
                    "path": key,
                    "local_md5": local_md5,
                    "server_md5": info.md5_hex,
                },
            )
        logger.info(
            "aws.write",
            key=key,
            size_bytes=len(data),
            content_type=content_type,
        )
        return info

    # ──────────────────────────────────────────────────────────────────
    # List
    # ──────────────────────────────────────────────────────────────────
    async def list_prefix(self, prefix: str) -> AsyncIterator[BlobInfo]:
        if prefix.startswith("s3://"):
            parsed = urlparse(prefix)
            if parsed.netloc != self._bucket:
                raise ValueError(
                    f"URI bucket {parsed.netloc!r} does not match this client's "
                    f"bucket {self._bucket!r}"
                )
            bare = parsed.path.lstrip("/")
        else:
            bare = prefix.lstrip("/")

        try:
            async with self._s3() as s3:
                paginator = s3.get_paginator("list_objects_v2")
                async for page in paginator.paginate(Bucket=self._bucket, Prefix=bare):
                    for item in page.get("Contents", []) or []:
                        last_modified = item.get("LastModified") or datetime.now(timezone.utc)
                        if last_modified.tzinfo is None:
                            last_modified = last_modified.replace(tzinfo=timezone.utc)
                        yield BlobInfo(
                            uri=self._uri(item["Key"]),
                            size_bytes=int(item.get("Size") or 0),
                            md5_hex=_etag_to_md5_hex(item.get("ETag")),
                            content_type=None,  # list_objects_v2 doesn't return it
                            last_modified=last_modified,
                            metadata={},  # likewise not in list responses
                        )
        except ClientError as exc:
            raise self._translate(bare, exc) from exc

    # ──────────────────────────────────────────────────────────────────
    # Exists / Delete / Stat / Copy / Signed URL
    # ──────────────────────────────────────────────────────────────────
    async def exists(self, path: str) -> bool:
        key = self._resolve_path(path)
        try:
            async with self._s3() as s3:
                await s3.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                return False
            raise self._translate(key, exc) from exc

    async def delete(self, path: str) -> None:
        key = self._resolve_path(path)
        try:
            async with self._s3() as s3:
                # delete_object is idempotent — no error if the key is absent.
                await s3.delete_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise self._translate(key, exc) from exc

    async def stat(self, path: str) -> BlobInfo:
        key = self._resolve_path(path)
        try:
            async with self._s3() as s3:
                head = await s3.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            raise self._translate(key, exc) from exc
        return self._info_from_head(key, head)

    async def copy(self, source: str, dest: str) -> BlobInfo:
        src_key = self._resolve_path(source)
        dst_key = self._resolve_path(dest)
        try:
            async with self._s3() as s3:
                await s3.copy_object(
                    Bucket=self._bucket,
                    Key=dst_key,
                    CopySource={"Bucket": self._bucket, "Key": src_key},
                )
                head = await s3.head_object(Bucket=self._bucket, Key=dst_key)
        except ClientError as exc:
            raise self._translate(src_key, exc) from exc
        logger.info("aws.copy", source=src_key, dest=dst_key)
        return self._info_from_head(dst_key, head)

    _METHOD_TO_OP: Final[dict[str, str]] = {
        "GET": "get_object",
        "PUT": "put_object",
    }

    async def signed_url(
        self,
        path: str,
        expires_in: timedelta,
        method: str = "GET",
    ) -> str:
        method = method.upper()
        op = self._METHOD_TO_OP.get(method)
        if op is None:
            raise ValueError(f"S3 presigned URLs support only GET or PUT; got {method!r}")
        key = self._resolve_path(path)
        try:
            async with self._s3() as s3:
                url = await s3.generate_presigned_url(
                    ClientMethod=op,
                    Params={"Bucket": self._bucket, "Key": key},
                    ExpiresIn=int(expires_in.total_seconds()),
                )
        except ClientError as exc:
            raise self._translate(key, exc) from exc
        return str(url)
