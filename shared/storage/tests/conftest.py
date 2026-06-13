"""Shared fixtures and dict-backed fake StorageClient implementations.

Each fake satisfies the same :class:`shared.storage.client.StorageClient`
Protocol as the real backends, but stores data in an in-process dict.
Tests must NOT hit real cloud services. The fakes mirror the spirit of
the FakeBucket / FakeBlob / FakeClient classes in
``data-pipeline/cloud/test_upload_local_to_gcs.py`` — keep the suite
hermetic.

Backend flavor differences the fakes preserve:

* GCS fake: emits ``gs://`` URIs, computes a real MD5.
* Azure fake: emits HTTPS blob URIs, computes a real MD5.
* AWS fake: emits ``s3://`` URIs and supports per-key
  ``multipart=True`` injection to model the "ETag is not an MD5" quirk;
  when set, the resulting BlobInfo has ``md5_hex = None`` just as the
  real S3 backend would do.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from urllib.parse import urlparse

from shared.storage.exceptions import (
    AccessDeniedException,
    ObjectNotFoundException,
)
from shared.storage.types import BlobInfo


# ──────────────────────────────────────────────────────────────────────────
# Stored-object record. Used by every fake.
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class _Entry:
    data: bytes
    content_type: str | None
    metadata: dict[str, str]
    last_modified: datetime
    multipart: bool = False  # AWS-only flag — see FakeAWSStorageClient

    @property
    def md5_hex(self) -> str | None:
        if self.multipart:
            return None
        return hashlib.md5(self.data).hexdigest()

    @property
    def size_bytes(self) -> int:
        return len(self.data)


# ──────────────────────────────────────────────────────────────────────────
# Base dict-backed fake. Common behaviour shared by all three backends.
# ──────────────────────────────────────────────────────────────────────────
class _BaseFake:
    """Common state + behaviour. Subclasses override URI / path resolution."""

    def __init__(self) -> None:
        self._store: dict[str, _Entry] = {}
        # Names the fake should respond to with AccessDenied for testing.
        self._denied: set[str] = set()

    # Subclasses implement:
    def _uri(self, key: str) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def _resolve_path(self, path: str) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    # Helpers tests can use to set up scenarios.
    def deny_access_to(self, key: str) -> None:
        self._denied.add(key)

    def _check_access(self, key: str) -> None:
        if key in self._denied:
            raise AccessDeniedException(
                f"Access denied to {key}",
                details={"path": key},
            )

    def _make_info(self, key: str, entry: _Entry) -> BlobInfo:
        return BlobInfo(
            uri=self._uri(key),
            size_bytes=entry.size_bytes,
            md5_hex=entry.md5_hex,
            content_type=entry.content_type,
            last_modified=entry.last_modified,
            metadata=dict(entry.metadata),
        )

    # ── StorageClient protocol ──
    async def read_bytes(self, path: str) -> bytes:
        key = self._resolve_path(path)
        self._check_access(key)
        entry = self._store.get(key)
        if entry is None:
            raise ObjectNotFoundException(
                f"Object not found: {key}",
                details={"path": key},
            )
        return entry.data

    async def write_bytes(
        self,
        path: str,
        data: bytes,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> BlobInfo:
        key = self._resolve_path(path)
        self._check_access(key)
        entry = _Entry(
            data=bytes(data),
            content_type=content_type,
            metadata=dict(metadata or {}),
            last_modified=datetime.now(timezone.utc),
        )
        self._store[key] = entry
        return self._make_info(key, entry)

    async def list_prefix(self, prefix: str) -> AsyncIterator[BlobInfo]:
        # Accept full URI or bare prefix.
        try:
            bare = self._resolve_path(prefix)
        except ValueError:
            raise
        for key in sorted(self._store):
            if key.startswith(bare):
                yield self._make_info(key, self._store[key])

    async def exists(self, path: str) -> bool:
        key = self._resolve_path(path)
        self._check_access(key)  # surfaces 403 instead of silently False
        return key in self._store

    async def delete(self, path: str) -> None:
        key = self._resolve_path(path)
        self._check_access(key)
        self._store.pop(key, None)

    async def stat(self, path: str) -> BlobInfo:
        key = self._resolve_path(path)
        self._check_access(key)
        entry = self._store.get(key)
        if entry is None:
            raise ObjectNotFoundException(
                f"Object not found: {key}",
                details={"path": key},
            )
        return self._make_info(key, entry)

    async def copy(self, source: str, dest: str) -> BlobInfo:
        src_key = self._resolve_path(source)
        dst_key = self._resolve_path(dest)
        self._check_access(src_key)
        self._check_access(dst_key)
        entry = self._store.get(src_key)
        if entry is None:
            raise ObjectNotFoundException(
                f"Object not found: {src_key}",
                details={"path": src_key},
            )
        new_entry = _Entry(
            data=entry.data,
            content_type=entry.content_type,
            metadata=dict(entry.metadata),
            last_modified=datetime.now(timezone.utc),
            multipart=entry.multipart,
        )
        self._store[dst_key] = new_entry
        return self._make_info(dst_key, new_entry)

    async def signed_url(
        self,
        path: str,
        expires_in: timedelta,
        method: str = "GET",
    ) -> str:
        key = self._resolve_path(path)
        # Cheap representation — real backends do crypto here.
        return (
            f"{self._uri(key)}?fake-sig&method={method.upper()}"
            f"&expires_in={int(expires_in.total_seconds())}"
        )


# ──────────────────────────────────────────────────────────────────────────
# Backend-flavoured fakes
# ──────────────────────────────────────────────────────────────────────────
class FakeGCSStorageClient(_BaseFake):
    """In-memory StorageClient flavoured as GCS."""

    def __init__(self, bucket: str) -> None:
        super().__init__()
        self._bucket = bucket

    def _uri(self, key: str) -> str:
        return f"gs://{self._bucket}/{key}"

    def _resolve_path(self, path: str) -> str:
        if path.startswith("gs://"):
            parsed = urlparse(path)
            if parsed.netloc != self._bucket:
                raise ValueError(
                    f"URI bucket {parsed.netloc!r} does not match fake's bucket "
                    f"{self._bucket!r}"
                )
            return parsed.path.lstrip("/")
        return path.lstrip("/")


class FakeAzureStorageClient(_BaseFake):
    """In-memory StorageClient flavoured as Azure Blob."""

    def __init__(self, account: str, container: str) -> None:
        super().__init__()
        self._account = account
        self._container = container

    def _uri(self, key: str) -> str:
        return f"https://{self._account}.blob.core.windows.net/" f"{self._container}/{key}"

    def _resolve_path(self, path: str) -> str:
        if path.startswith("https://"):
            parsed = urlparse(path)
            expected_host = f"{self._account}.blob.core.windows.net"
            if parsed.netloc != expected_host:
                raise ValueError(
                    f"URI host {parsed.netloc!r} does not match fake's account "
                    f"{self._account!r}"
                )
            parts = parsed.path.lstrip("/").split("/", 1)
            if not parts or parts[0] != self._container:
                raise ValueError(
                    f"URI container does not match fake's container {self._container!r}"
                )
            return parts[1] if len(parts) > 1 else ""
        return path.lstrip("/")


class FakeAWSStorageClient(_BaseFake):
    """In-memory StorageClient flavoured as S3.

    Adds :meth:`write_multipart` so tests can model the "multipart ETag is
    not a flat MD5" quirk without involving any real SDK.
    """

    def __init__(self, bucket: str) -> None:
        super().__init__()
        self._bucket = bucket

    def _uri(self, key: str) -> str:
        return f"s3://{self._bucket}/{key}"

    def _resolve_path(self, path: str) -> str:
        if path.startswith("s3://"):
            parsed = urlparse(path)
            if parsed.netloc != self._bucket:
                raise ValueError(
                    f"URI bucket {parsed.netloc!r} does not match fake's bucket "
                    f"{self._bucket!r}"
                )
            return parsed.path.lstrip("/")
        return path.lstrip("/")

    async def write_multipart(
        self,
        path: str,
        data: bytes,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> BlobInfo:
        """Pretend this object was uploaded via multipart — md5_hex will be None."""
        key = self._resolve_path(path)
        entry = _Entry(
            data=bytes(data),
            content_type=content_type,
            metadata=dict(metadata or {}),
            last_modified=datetime.now(timezone.utc),
            multipart=True,
        )
        self._store[key] = entry
        return self._make_info(key, entry)
