"""Unified async multi-cloud storage adapter.

Service code uses this package as the ONLY way to talk to object storage.
It hides whether the underlying backend is GCS, Azure Blob, or AWS S3.

Typical usage::

    from shared.storage import StorageClient, BlobInfo

    # Cloud-bound at deployment time via env vars.
    storage = StorageClient.from_env()

    # Or explicit URI.
    storage = StorageClient.from_uri("gs://maisys-data-dev")

    data = await storage.read_bytes("raw/drugs_com/page-1.html")
    info = await storage.write_bytes("processed/output.json", payload)
    async for blob in storage.list_prefix("manifests/"):
        ...

The :class:`StorageClient` exposed here is the FACTORY (with
``from_uri`` / ``from_env`` static methods). The PROTOCOL of the same
name lives in ``shared.storage.client``; it's exposed here as
``StorageClientProtocol`` for type hints in service code that wants to
annotate a parameter as accepting any backend.
"""

from shared.storage.aws import AWSStorageClient
from shared.storage.azure import AzureStorageClient
from shared.storage.client import StorageClient as StorageClientProtocol
from shared.storage.exceptions import (
    AccessDeniedException,
    ChecksumMismatchException,
    ObjectNotFoundException,
    StorageException,
)
from shared.storage.factory import StorageClient
from shared.storage.gcs import GCSStorageClient
from shared.storage.types import BlobInfo

__all__ = [
    "AWSStorageClient",
    "AccessDeniedException",
    "AzureStorageClient",
    "BlobInfo",
    "ChecksumMismatchException",
    "GCSStorageClient",
    "ObjectNotFoundException",
    "StorageClient",
    "StorageClientProtocol",
    "StorageException",
]
