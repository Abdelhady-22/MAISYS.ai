"""Factory for resolving a concrete StorageClient from URI or env vars.

Service code should never construct a backend directly — call
:func:`from_uri` or :func:`from_env`. This keeps the cloud-binding
decision in one place and makes it easy to switch backends without
service-code changes.

The class :class:`StorageClient` here is the FACTORY entry point. The
PROTOCOL named ``StorageClient`` lives in :mod:`shared.storage.client`
to keep concerns separate; the two are re-exported together from the
package root.
"""

from __future__ import annotations

import os
import re
from typing import Final
from urllib.parse import urlparse

from shared.storage.aws import AWSStorageClient
from shared.storage.azure import AzureStorageClient
from shared.storage.client import StorageClient as StorageClientProtocol
from shared.storage.gcs import GCSStorageClient

_AZURE_BLOB_HOST_RE: Final[re.Pattern[str]] = re.compile(
    r"^(?P<account>[a-z0-9]+)\.blob\.core\.windows\.net$"
)

_SUPPORTED_URI_SHAPES: Final[str] = (
    "Supported URI shapes:\n"
    "  - gs://bucket/path\n"
    "  - https://<account>.blob.core.windows.net/<container>/path\n"
    "  - s3://bucket/path"
)


class StorageClient:
    """Factory facade. Use the static methods; do not instantiate."""

    def __init__(self) -> None:
        raise TypeError(
            "StorageClient is a factory facade; call StorageClient.from_uri "
            "or StorageClient.from_env to obtain a backend."
        )

    @staticmethod
    def from_uri(uri: str) -> StorageClientProtocol:
        """Resolve a backend from a canonical URI.

        Dispatches on the scheme:

        * ``gs://bucket/...`` → :class:`GCSStorageClient`
        * ``https://<account>.blob.core.windows.net/<container>/...`` →
          :class:`AzureStorageClient`
        * ``s3://bucket/...`` → :class:`AWSStorageClient`
        """
        parsed = urlparse(uri)
        scheme = parsed.scheme.lower()
        if scheme == "gs":
            if not parsed.netloc:
                raise ValueError(f"gs:// URI missing bucket: {uri!r}")
            return GCSStorageClient(bucket=parsed.netloc)
        if scheme == "s3":
            if not parsed.netloc:
                raise ValueError(f"s3:// URI missing bucket: {uri!r}")
            return AWSStorageClient(bucket=parsed.netloc)
        if scheme == "https":
            match = _AZURE_BLOB_HOST_RE.match(parsed.netloc)
            if match is None:
                raise ValueError(
                    f"Unsupported HTTPS host {parsed.netloc!r}.\n" f"{_SUPPORTED_URI_SHAPES}"
                )
            path_parts = parsed.path.lstrip("/").split("/", 1)
            if not path_parts or not path_parts[0]:
                raise ValueError(
                    f"Azure URI missing container: {uri!r}\n" f"{_SUPPORTED_URI_SHAPES}"
                )
            return AzureStorageClient(
                account=match.group("account"),
                container=path_parts[0],
            )
        raise ValueError(
            f"Unsupported URI scheme {scheme!r} in {uri!r}.\n" f"{_SUPPORTED_URI_SHAPES}"
        )

    @staticmethod
    def from_env() -> StorageClientProtocol:
        """Resolve a backend from environment variables.

        Reads ``CLOUD_PROVIDER`` (one of ``gcp``, ``azure``, ``aws``) and
        the provider-specific config:

        * gcp:   ``STORAGE_BUCKET`` (required)
        * azure: ``STORAGE_ACCOUNT`` + ``STORAGE_CONTAINER`` (both required)
        * aws:   ``STORAGE_BUCKET`` (required), ``AWS_REGION`` (optional)

        Raises ``RuntimeError`` naming the exact missing variable when a
        required one is absent.
        """
        provider = (os.environ.get("CLOUD_PROVIDER") or "").lower()
        if not provider:
            raise RuntimeError("CLOUD_PROVIDER is not set. Set it to one of: gcp, azure, aws.")

        if provider == "gcp":
            bucket = os.environ.get("STORAGE_BUCKET")
            if not bucket:
                raise RuntimeError("CLOUD_PROVIDER=gcp requires STORAGE_BUCKET to be set.")
            return GCSStorageClient(bucket=bucket)

        if provider == "azure":
            account = os.environ.get("STORAGE_ACCOUNT")
            container = os.environ.get("STORAGE_CONTAINER")
            missing = [
                name
                for name, value in [
                    ("STORAGE_ACCOUNT", account),
                    ("STORAGE_CONTAINER", container),
                ]
                if not value
            ]
            if missing:
                raise RuntimeError(
                    f"CLOUD_PROVIDER=azure requires {' and '.join(missing)} to be set."
                )
            assert account is not None and container is not None  # for mypy
            return AzureStorageClient(account=account, container=container)

        if provider == "aws":
            bucket = os.environ.get("STORAGE_BUCKET")
            if not bucket:
                raise RuntimeError("CLOUD_PROVIDER=aws requires STORAGE_BUCKET to be set.")
            region = os.environ.get("AWS_REGION") or None
            return AWSStorageClient(bucket=bucket, region=region)

        raise RuntimeError(f"CLOUD_PROVIDER={provider!r} is unknown. Set one of: gcp, azure, aws.")
