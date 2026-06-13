"""StorageClient Protocol — the unified async interface across GCS, Azure, AWS.

Service code depends on this Protocol, never on a concrete backend. Resolve
a concrete backend via :mod:`shared.storage.factory`.

Path resolution
---------------
Every method accepts a ``path`` argument that may be either:

* A path relative to the client's configured bucket/container (e.g.
  ``"raw/drugs_com/page-1.html"``).
* A full canonical URI (``gs://``, ``https://*.blob...``, ``s3://``). When
  a full URI is passed, the backend MUST verify the bucket/container in
  the URI matches its own configured scope. If it doesn't,
  ``ValueError`` is raised — silent cross-bucket dispatch is a footgun.

Backends are responsible for normalizing both forms before calling the
underlying SDK.
"""

from __future__ import annotations

from datetime import timedelta
from typing import AsyncIterator, Protocol, runtime_checkable

from shared.storage.types import BlobInfo


@runtime_checkable
class StorageClient(Protocol):
    """Unified async interface across GCS, Azure Blob, and AWS S3.

    All methods raise :class:`shared.storage.exceptions.StorageException`
    or one of its subclasses on backend failure. ``ObjectNotFoundException``
    is raised for missing objects; ``AccessDeniedException`` for permission
    failures; ``ChecksumMismatchException`` from ``write_bytes`` when the
    backend's server-computed hash disagrees with the local one.
    """

    async def read_bytes(self, path: str) -> bytes:
        """Read an object's full content into memory.

        Backends stream large objects internally (no hard limit imposed by
        this API), but callers requesting very large objects should
        consider chunked retrieval at the SDK level instead.
        """
        ...

    async def write_bytes(
        self,
        path: str,
        data: bytes,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> BlobInfo:
        """Write bytes to ``path``. Overwrites any existing object.

        Backends use resumable / multipart upload internally for large
        payloads. Returns the resulting :class:`BlobInfo` (with
        server-computed metadata).
        """
        ...

    def list_prefix(self, prefix: str) -> AsyncIterator[BlobInfo]:
        """Yield BlobInfo for every object whose key starts with ``prefix``.

        Pagination is handled internally — the iterator paginates lazily
        so memory stays bounded regardless of how many objects match.
        Returns the async iterator directly (not via ``async def``) so
        callers can use ``async for`` ergonomically.
        """
        ...

    async def exists(self, path: str) -> bool:
        """Return True if an object exists at ``path``, else False.

        ``AccessDeniedException`` is raised on permission failures (rather
        than swallowed as False) so misconfigured credentials surface
        loudly instead of silently looking like an empty bucket.
        """
        ...

    async def delete(self, path: str) -> None:
        """Delete the object at ``path``. Idempotent — no error if absent."""
        ...

    async def stat(self, path: str) -> BlobInfo:
        """Return :class:`BlobInfo` for ``path`` without downloading content."""
        ...

    async def copy(self, source: str, dest: str) -> BlobInfo:
        """Server-side copy from ``source`` to ``dest`` within the same backend.

        Both paths must resolve to the SAME backend (and the same
        bucket/container scope of this client). Cross-cloud copies are NOT
        supported here — use the per-cloud sync scripts in
        ``data-pipeline/cloud/`` for that.
        """
        ...

    async def signed_url(
        self,
        path: str,
        expires_in: timedelta,
        method: str = "GET",
    ) -> str:
        """Issue a time-limited pre-signed URL granting access without credentials.

        ``method`` is the HTTP verb the URL grants ("GET", "PUT", etc.).
        Backends translate to their native equivalent (GCS signed URLs,
        Azure SAS tokens, S3 presigned URLs).
        """
        ...
