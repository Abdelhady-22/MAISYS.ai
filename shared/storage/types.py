"""Shared types for the storage adapter.

BlobInfo is the cross-cloud metadata envelope returned by every backend.
It carries the minimum every consumer cares about — URI, size, hash where
available, content type, modification time, and arbitrary cloud-specific
custom metadata. Backend quirks (e.g. S3 multipart objects without a
verifiable MD5) are surfaced as ``md5_hex = None`` rather than hidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class BlobInfo:
    """Metadata for a single stored object, returned from write/stat/list.

    Attributes:
        uri: Canonical URI of the object. ``gs://bucket/path``,
            ``https://<account>.blob.core.windows.net/<container>/path``,
            or ``s3://bucket/path``.
        size_bytes: Object size in bytes.
        md5_hex: Lowercase hex MD5 of the object content, when the backend
            exposes it. ``None`` for S3 multipart-uploaded objects (their
            ETag is not a plain MD5); ``None`` if the backend returned no
            hash.
        content_type: MIME type if set on the object; ``None`` otherwise.
        last_modified: Server-side last-modified timestamp (UTC).
        metadata: Arbitrary user-defined metadata attached to the object.
            For GCS this is ``blob.metadata``; for Azure
            ``BlobProperties.metadata``; for S3 the object's ``Metadata``
            map. Cloud-specific reserved metadata (e.g. S3's
            ``x-amz-server-side-encryption``) is NOT exposed here.
    """

    uri: str
    size_bytes: int
    md5_hex: str | None
    content_type: str | None
    last_modified: datetime
    metadata: dict[str, str] = field(default_factory=dict)
