"""GCS backend implementation of StorageClient.

Wraps the synchronous ``google-cloud-storage`` client. Every public method
is async; SDK calls are dispatched via ``asyncio.to_thread`` so the event
loop is never blocked. The async GCS client (``google.cloud.storage.aio``)
is intentionally avoided — at time of writing it is still marked
experimental and missing functionality the sync client has.

Streaming threshold (100 MB) applies to both reads and writes:
* Below the threshold, the single-call SDK methods are used.
* At or above the threshold, ``blob.open()`` streams chunks so the entire
  payload never lives in memory simultaneously.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Final
from urllib.parse import urlparse

from google.api_core import exceptions as gcs_exceptions
from google.cloud import storage

from shared.logger import get_logger
from shared.storage.exceptions import (
    AccessDeniedException,
    ChecksumMismatchException,
    ObjectNotFoundException,
    StorageException,
)
from shared.storage.types import BlobInfo

logger = get_logger(__name__)

# Below this size the single-shot SDK methods are used. At/above it, we
# stream so the entire payload never lives in memory.
STREAMING_THRESHOLD_BYTES: Final[int] = 100 * 1024 * 1024  # 100 MB

# Page size for list operations.
_LIST_PAGE_SIZE: Final[int] = 1000


def _md5_b64_to_hex(b64: str | None) -> str | None:
    """Convert GCS's base64-encoded MD5 to lowercase hex.

    GCS exposes ``blob.md5_hash`` as a base64 string (e.g. ``"r1eAY..."``).
    Our cross-cloud convention is lowercase hex. Returns None if the input
    is None or not a valid base64-encoded 16-byte digest.
    """
    if b64 is None:
        return None
    try:
        digest = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError):
        return None
    if len(digest) != 16:
        return None
    return digest.hex()


class GCSStorageClient:
    """StorageClient implementation backed by Google Cloud Storage."""

    def __init__(
        self,
        bucket: str,
        *,
        client: storage.Client | None = None,
    ) -> None:
        """Construct a GCS-backed StorageClient.

        Args:
            bucket: The GCS bucket name this client is scoped to.
            client: Optional pre-built ``storage.Client``. When None,
                Application Default Credentials are used.
        """
        self._bucket_name = bucket
        self._client = client if client is not None else storage.Client()
        self._bucket = self._client.bucket(bucket)

    # ──────────────────────────────────────────────────────────────────
    # Path resolution
    # ──────────────────────────────────────────────────────────────────
    def _resolve_path(self, path: str) -> str:
        """Accept either a bare path or a ``gs://bucket/path`` URI.

        Full URIs must reference THIS client's bucket; otherwise raise
        ValueError. Returns the bare blob name (no leading slash).
        """
        if path.startswith("gs://"):
            parsed = urlparse(path)
            if parsed.netloc != self._bucket_name:
                raise ValueError(
                    f"URI bucket {parsed.netloc!r} does not match this client's "
                    f"bucket {self._bucket_name!r}"
                )
            return parsed.path.lstrip("/")
        return path.lstrip("/")

    def _uri(self, blob_name: str) -> str:
        return f"gs://{self._bucket_name}/{blob_name}"

    # ──────────────────────────────────────────────────────────────────
    # SDK exception translation
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _translate(path: str, exc: BaseException) -> StorageException:
        """Map a GCS SDK exception to our hierarchy. Preserves cause."""
        if isinstance(exc, gcs_exceptions.NotFound):
            return ObjectNotFoundException(
                f"Object not found: {path}",
                details={"path": path},
                cause=exc,
            )
        if isinstance(exc, gcs_exceptions.Forbidden):
            return AccessDeniedException(
                f"Access denied to {path}",
                details={"path": path},
                cause=exc,
            )
        return StorageException(
            f"GCS error on {path}: {exc}",
            details={"path": path, "exception_type": type(exc).__name__},
            cause=exc,
        )

    # ──────────────────────────────────────────────────────────────────
    # BlobInfo construction from a (loaded) Blob
    # ──────────────────────────────────────────────────────────────────
    def _blob_info(self, blob: storage.Blob) -> BlobInfo:
        last_modified = blob.updated or blob.time_created
        if last_modified is None:
            last_modified = datetime.now(timezone.utc)
        return BlobInfo(
            uri=self._uri(blob.name or ""),
            size_bytes=int(blob.size or 0),
            md5_hex=_md5_b64_to_hex(blob.md5_hash),
            content_type=blob.content_type,
            last_modified=last_modified,
            metadata=dict(blob.metadata or {}),
        )

    # ──────────────────────────────────────────────────────────────────
    # Read
    # ──────────────────────────────────────────────────────────────────
    async def read_bytes(self, path: str) -> bytes:
        blob_name = self._resolve_path(path)
        try:
            return await asyncio.to_thread(self._read_bytes_sync, blob_name)
        except StorageException:
            raise
        except gcs_exceptions.GoogleAPICallError as exc:
            raise self._translate(blob_name, exc) from exc

    def _read_bytes_sync(self, blob_name: str) -> bytes:
        blob = self._bucket.blob(blob_name)
        # reload() populates size, md5_hash etc; also raises NotFound early.
        blob.reload(client=self._client)
        size = int(blob.size or 0)
        if size < STREAMING_THRESHOLD_BYTES:
            data = blob.download_as_bytes(client=self._client)
            logger.debug(
                "gcs.read",
                blob=blob_name,
                size_bytes=size,
                mode="single",
            )
            return bytes(data)
        # Streaming path.
        chunks: list[bytes] = []
        with blob.open("rb") as stream:
            while True:
                chunk = stream.read(8 * 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
        logger.info(
            "gcs.read",
            blob=blob_name,
            size_bytes=size,
            mode="streaming",
        )
        return b"".join(chunks)

    # ──────────────────────────────────────────────────────────────────
    # Write
    # ──────────────────────────────────────────────────────────────────
    async def write_bytes(
        self,
        path: str,
        data: bytes,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> BlobInfo:
        blob_name = self._resolve_path(path)
        local_md5 = hashlib.md5(data).hexdigest()
        try:
            return await asyncio.to_thread(
                self._write_bytes_sync,
                blob_name,
                data,
                content_type,
                metadata,
                local_md5,
            )
        except StorageException:
            raise
        except gcs_exceptions.GoogleAPICallError as exc:
            raise self._translate(blob_name, exc) from exc

    def _write_bytes_sync(
        self,
        blob_name: str,
        data: bytes,
        content_type: str | None,
        metadata: dict[str, str] | None,
        local_md5: str,
    ) -> BlobInfo:
        blob = self._bucket.blob(blob_name)
        if metadata:
            blob.metadata = metadata
        # upload_from_string transparently uses resumable upload above
        # ~8 MB. For ≥100 MB it always does.
        blob.upload_from_string(
            data,
            content_type=content_type,
            client=self._client,
        )
        blob.reload(client=self._client)
        server_md5_hex = _md5_b64_to_hex(blob.md5_hash)
        if server_md5_hex is not None and server_md5_hex != local_md5:
            raise ChecksumMismatchException(
                f"MD5 mismatch on write to {blob_name}: "
                f"local={local_md5}, server={server_md5_hex}",
                details={
                    "path": blob_name,
                    "local_md5": local_md5,
                    "server_md5": server_md5_hex,
                },
            )
        logger.info(
            "gcs.write",
            blob=blob_name,
            size_bytes=len(data),
            content_type=content_type,
        )
        return self._blob_info(blob)

    # ──────────────────────────────────────────────────────────────────
    # List (async iterator)
    # ──────────────────────────────────────────────────────────────────
    async def list_prefix(self, prefix: str) -> AsyncIterator[BlobInfo]:
        # Normalize prefix: bare or full URI both accepted.
        if prefix.startswith("gs://"):
            parsed = urlparse(prefix)
            if parsed.netloc != self._bucket_name:
                raise ValueError(
                    f"URI bucket {parsed.netloc!r} does not match this client's "
                    f"bucket {self._bucket_name!r}"
                )
            bare_prefix = parsed.path.lstrip("/")
        else:
            bare_prefix = prefix.lstrip("/")

        page_token: str | None = None
        while True:
            try:
                page_blobs, page_token = await asyncio.to_thread(
                    self._list_page_sync,
                    bare_prefix,
                    page_token,
                )
            except gcs_exceptions.GoogleAPICallError as exc:
                raise self._translate(bare_prefix, exc) from exc
            for blob in page_blobs:
                yield self._blob_info(blob)
            if page_token is None:
                return

    def _list_page_sync(
        self,
        prefix: str,
        page_token: str | None,
    ) -> tuple[list[storage.Blob], str | None]:
        iterator = self._client.list_blobs(
            self._bucket_name,
            prefix=prefix,
            page_token=page_token,
            max_results=_LIST_PAGE_SIZE,
        )
        # Iterate ONE page only; do not exhaust the iterator.
        page = next(iterator.pages, None)
        if page is None:
            return [], None
        return list(page), iterator.next_page_token or None

    # ──────────────────────────────────────────────────────────────────
    # Exists / Delete / Stat / Copy / Signed URL
    # ──────────────────────────────────────────────────────────────────
    async def exists(self, path: str) -> bool:
        blob_name = self._resolve_path(path)
        try:
            return await asyncio.to_thread(self._exists_sync, blob_name)
        except gcs_exceptions.Forbidden as exc:
            raise self._translate(blob_name, exc) from exc
        except gcs_exceptions.GoogleAPICallError as exc:
            raise self._translate(blob_name, exc) from exc

    def _exists_sync(self, blob_name: str) -> bool:
        return bool(self._bucket.blob(blob_name).exists(client=self._client))

    async def delete(self, path: str) -> None:
        blob_name = self._resolve_path(path)
        try:
            await asyncio.to_thread(self._delete_sync, blob_name)
        except gcs_exceptions.NotFound:
            return  # idempotent
        except gcs_exceptions.GoogleAPICallError as exc:
            raise self._translate(blob_name, exc) from exc

    def _delete_sync(self, blob_name: str) -> None:
        self._bucket.blob(blob_name).delete(client=self._client)

    async def stat(self, path: str) -> BlobInfo:
        blob_name = self._resolve_path(path)
        try:
            return await asyncio.to_thread(self._stat_sync, blob_name)
        except gcs_exceptions.GoogleAPICallError as exc:
            raise self._translate(blob_name, exc) from exc

    def _stat_sync(self, blob_name: str) -> BlobInfo:
        blob = self._bucket.blob(blob_name)
        blob.reload(client=self._client)
        return self._blob_info(blob)

    async def copy(self, source: str, dest: str) -> BlobInfo:
        src_name = self._resolve_path(source)
        dst_name = self._resolve_path(dest)
        try:
            return await asyncio.to_thread(self._copy_sync, src_name, dst_name)
        except gcs_exceptions.GoogleAPICallError as exc:
            raise self._translate(src_name, exc) from exc

    def _copy_sync(self, src_name: str, dst_name: str) -> BlobInfo:
        src_blob = self._bucket.blob(src_name)
        # copy_blob returns the destination Blob.
        dst_blob = self._bucket.copy_blob(
            src_blob,
            self._bucket,
            new_name=dst_name,
            client=self._client,
        )
        dst_blob.reload(client=self._client)
        logger.info("gcs.copy", source=src_name, dest=dst_name)
        return self._blob_info(dst_blob)

    _METHOD_RE = re.compile(r"^(GET|PUT|POST|DELETE|HEAD)$")

    async def signed_url(
        self,
        path: str,
        expires_in: timedelta,
        method: str = "GET",
    ) -> str:
        method = method.upper()
        if not self._METHOD_RE.match(method):
            raise ValueError(f"Unsupported signed_url method: {method}")
        blob_name = self._resolve_path(path)
        try:
            return await asyncio.to_thread(
                self._signed_url_sync,
                blob_name,
                expires_in,
                method,
            )
        except gcs_exceptions.GoogleAPICallError as exc:
            raise self._translate(blob_name, exc) from exc

    def _signed_url_sync(
        self,
        blob_name: str,
        expires_in: timedelta,
        method: str,
    ) -> str:
        blob = self._bucket.blob(blob_name)
        url = blob.generate_signed_url(
            version="v4",
            expiration=expires_in,
            method=method,
        )
        return str(url)
