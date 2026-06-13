"""Azure Blob Storage backend implementation of StorageClient.

Wraps the native-async ``azure.storage.blob.aio`` SDK. Auth uses
``DefaultAzureCredential`` by default:

* Locally:    ``az login`` provides the credentials.
* In AKS:     Managed Identity (via Workload Identity Federation).
* In GitHub Actions: OIDC → Federated Credential → UAI.

Signed URLs are generated as Shared Access Signatures (SAS tokens). A
user-delegation key is preferred when an AAD-backed credential is in use,
falling back to account-key signing when the credential exposes one.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Final

from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceExistsError,
    ResourceNotFoundError,
)
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob import (
    BlobSasPermissions,
    ContainerSasPermissions,
    generate_blob_sas,
)
from azure.storage.blob.aio import BlobServiceClient

from shared.logger import get_logger
from shared.storage.exceptions import (
    AccessDeniedException,
    ChecksumMismatchException,
    ObjectNotFoundException,
    StorageException,
)
from shared.storage.types import BlobInfo

logger = get_logger(__name__)

# Azure SDK chunked upload kicks in above this size — kept for parity with
# the GCS backend's threshold-aware logging.
STREAMING_THRESHOLD_BYTES: Final[int] = 100 * 1024 * 1024  # 100 MB

_HTTPS_BLOB_HOST_RE: Final[re.Pattern[str]] = re.compile(
    r"^https://(?P<account>[a-z0-9]+)\.blob\.core\.windows\.net/(?P<container>[^/]+)(?:/(?P<path>.*))?$"
)


class AzureStorageClient:
    """StorageClient implementation backed by Azure Blob Storage."""

    def __init__(
        self,
        account: str,
        container: str,
        *,
        credential: Any | None = None,
    ) -> None:
        """Construct an Azure-backed StorageClient.

        Args:
            account: Azure Storage account name.
            container: Container within the account.
            credential: Optional credential supporting the
                ``azure-core`` async TokenCredential protocol. When None,
                ``DefaultAzureCredential`` is used. Typed as ``Any`` here
                so service callers can pass any of the credential types
                the SDK accepts without us re-declaring the union.
        """
        self._account = account
        self._container = container
        self._credential: Any = credential if credential is not None else DefaultAzureCredential()
        self._service = BlobServiceClient(
            account_url=f"https://{account}.blob.core.windows.net",
            credential=self._credential,
        )
        self._container_client = self._service.get_container_client(container)

    # ──────────────────────────────────────────────────────────────────
    # Path resolution
    # ──────────────────────────────────────────────────────────────────
    def _resolve_path(self, path: str) -> str:
        if path.startswith("https://"):
            match = _HTTPS_BLOB_HOST_RE.match(path)
            if match is None:
                raise ValueError(f"URI does not look like an Azure Blob URL: {path!r}")
            if match.group("account") != self._account:
                raise ValueError(
                    f"URI account {match.group('account')!r} does not match "
                    f"this client's account {self._account!r}"
                )
            if match.group("container") != self._container:
                raise ValueError(
                    f"URI container {match.group('container')!r} does not "
                    f"match this client's container {self._container!r}"
                )
            return (match.group("path") or "").lstrip("/")
        return path.lstrip("/")

    def _uri(self, blob_name: str) -> str:
        return f"https://{self._account}.blob.core.windows.net/" f"{self._container}/{blob_name}"

    # ──────────────────────────────────────────────────────────────────
    # SDK exception translation
    # ──────────────────────────────────────────────────────────────────
    @staticmethod
    def _translate(path: str, exc: BaseException) -> StorageException:
        if isinstance(exc, ResourceNotFoundError):
            return ObjectNotFoundException(
                f"Object not found: {path}",
                details={"path": path},
                cause=exc,
            )
        if isinstance(exc, ClientAuthenticationError):
            return AccessDeniedException(
                f"Access denied to {path}",
                details={"path": path},
                cause=exc,
            )
        if isinstance(exc, HttpResponseError) and exc.status_code == 403:
            return AccessDeniedException(
                f"Access denied to {path}",
                details={"path": path},
                cause=exc,
            )
        if isinstance(exc, HttpResponseError) and exc.status_code == 404:
            return ObjectNotFoundException(
                f"Object not found: {path}",
                details={"path": path},
                cause=exc,
            )
        return StorageException(
            f"Azure error on {path}: {exc}",
            details={"path": path, "exception_type": type(exc).__name__},
            cause=exc,
        )

    # ──────────────────────────────────────────────────────────────────
    # BlobInfo construction from BlobProperties
    # ──────────────────────────────────────────────────────────────────
    def _blob_info_from_props(self, blob_name: str, props: object) -> BlobInfo:
        # ``props`` is an azure.storage.blob.BlobProperties — typed loosely
        # because the SDK does not export the type usefully for static
        # consumers. All fields below are documented stable attributes.
        size_bytes = int(getattr(props, "size", 0) or 0)
        last_modified = getattr(props, "last_modified", None) or datetime.now(timezone.utc)
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=timezone.utc)
        content_settings = getattr(props, "content_settings", None)
        content_type: str | None = None
        md5_hex: str | None = None
        if content_settings is not None:
            content_type = getattr(content_settings, "content_type", None)
            md5_bytes = getattr(content_settings, "content_md5", None)
            if md5_bytes is not None and len(md5_bytes) == 16:
                md5_hex = bytes(md5_bytes).hex()
        metadata = dict(getattr(props, "metadata", None) or {})
        return BlobInfo(
            uri=self._uri(blob_name),
            size_bytes=size_bytes,
            md5_hex=md5_hex,
            content_type=content_type,
            last_modified=last_modified,
            metadata=metadata,
        )

    # ──────────────────────────────────────────────────────────────────
    # Read / Write
    # ──────────────────────────────────────────────────────────────────
    async def read_bytes(self, path: str) -> bytes:
        blob_name = self._resolve_path(path)
        blob_client = self._container_client.get_blob_client(blob_name)
        try:
            downloader = await blob_client.download_blob()
            data = await downloader.readall()
        except (HttpResponseError, ResourceNotFoundError, ClientAuthenticationError) as exc:
            raise self._translate(blob_name, exc) from exc
        size = len(data)
        logger.info(
            "azure.read",
            blob=blob_name,
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
        blob_name = self._resolve_path(path)
        local_md5_bytes = hashlib.md5(data).digest()
        blob_client = self._container_client.get_blob_client(blob_name)
        # Late import so optional dependency on ContentSettings stays here.
        from azure.storage.blob import ContentSettings

        content_settings = ContentSettings(
            content_type=content_type,
            content_md5=bytearray(local_md5_bytes),
        )
        try:
            await blob_client.upload_blob(
                data,
                overwrite=True,
                content_settings=content_settings,
                metadata=metadata,
            )
            props = await blob_client.get_blob_properties()
        except (HttpResponseError, ClientAuthenticationError) as exc:
            raise self._translate(blob_name, exc) from exc

        info = self._blob_info_from_props(blob_name, props)
        if info.md5_hex is not None and info.md5_hex != local_md5_bytes.hex():
            raise ChecksumMismatchException(
                f"MD5 mismatch on write to {blob_name}: "
                f"local={local_md5_bytes.hex()}, server={info.md5_hex}",
                details={
                    "path": blob_name,
                    "local_md5": local_md5_bytes.hex(),
                    "server_md5": info.md5_hex,
                },
            )
        logger.info(
            "azure.write",
            blob=blob_name,
            size_bytes=len(data),
            content_type=content_type,
        )
        return info

    # ──────────────────────────────────────────────────────────────────
    # List
    # ──────────────────────────────────────────────────────────────────
    async def list_prefix(self, prefix: str) -> AsyncIterator[BlobInfo]:
        if prefix.startswith("https://"):
            match = _HTTPS_BLOB_HOST_RE.match(prefix)
            if (
                match is None
                or match.group("account") != self._account
                or match.group("container") != self._container
            ):
                raise ValueError(
                    f"List prefix URI {prefix!r} does not match this client's scope "
                    f"({self._account}/{self._container})"
                )
            bare_prefix = (match.group("path") or "").lstrip("/")
        else:
            bare_prefix = prefix.lstrip("/")

        try:
            async for blob in self._container_client.list_blobs(name_starts_with=bare_prefix):
                yield self._blob_info_from_props(blob.name, blob)
        except (HttpResponseError, ClientAuthenticationError) as exc:
            raise self._translate(bare_prefix, exc) from exc

    # ──────────────────────────────────────────────────────────────────
    # Exists / Delete / Stat / Copy / Signed URL
    # ──────────────────────────────────────────────────────────────────
    async def exists(self, path: str) -> bool:
        blob_name = self._resolve_path(path)
        blob_client = self._container_client.get_blob_client(blob_name)
        try:
            return bool(await blob_client.exists())
        except ClientAuthenticationError as exc:
            raise self._translate(blob_name, exc) from exc
        except HttpResponseError as exc:
            raise self._translate(blob_name, exc) from exc

    async def delete(self, path: str) -> None:
        blob_name = self._resolve_path(path)
        blob_client = self._container_client.get_blob_client(blob_name)
        try:
            await blob_client.delete_blob()
        except ResourceNotFoundError:
            return  # idempotent
        except (HttpResponseError, ClientAuthenticationError) as exc:
            raise self._translate(blob_name, exc) from exc

    async def stat(self, path: str) -> BlobInfo:
        blob_name = self._resolve_path(path)
        blob_client = self._container_client.get_blob_client(blob_name)
        try:
            props = await blob_client.get_blob_properties()
        except (HttpResponseError, ResourceNotFoundError, ClientAuthenticationError) as exc:
            raise self._translate(blob_name, exc) from exc
        return self._blob_info_from_props(blob_name, props)

    async def copy(self, source: str, dest: str) -> BlobInfo:
        src_name = self._resolve_path(source)
        dst_name = self._resolve_path(dest)
        src_client = self._container_client.get_blob_client(src_name)
        dst_client = self._container_client.get_blob_client(dst_name)
        try:
            src_url = src_client.url
            await dst_client.start_copy_from_url(src_url, requires_sync=True)
            props = await dst_client.get_blob_properties()
        except (HttpResponseError, ClientAuthenticationError, ResourceExistsError) as exc:
            raise self._translate(src_name, exc) from exc
        logger.info("azure.copy", source=src_name, dest=dst_name)
        return self._blob_info_from_props(dst_name, props)

    _METHOD_RE = re.compile(r"^(GET|PUT)$")

    async def signed_url(
        self,
        path: str,
        expires_in: timedelta,
        method: str = "GET",
    ) -> str:
        method = method.upper()
        if not self._METHOD_RE.match(method):
            raise ValueError(f"Azure SAS supports only GET or PUT; got {method!r}")
        blob_name = self._resolve_path(path)
        # User-delegation SAS works when credential is AAD-backed (the
        # default). Fetch a user-delegation key valid for the requested
        # window and sign the SAS with it.
        expiry = datetime.now(timezone.utc) + expires_in
        try:
            key_start = datetime.now(timezone.utc) - timedelta(minutes=5)
            udk = await self._service.get_user_delegation_key(
                key_start_time=key_start,
                key_expiry_time=expiry,
            )
        except (HttpResponseError, ClientAuthenticationError) as exc:
            raise self._translate(blob_name, exc) from exc

        permissions = (
            BlobSasPermissions(read=True)
            if method == "GET"
            else BlobSasPermissions(write=True, create=True)
        )
        sas = generate_blob_sas(
            account_name=self._account,
            container_name=self._container,
            blob_name=blob_name,
            user_delegation_key=udk,
            permission=permissions,
            expiry=expiry,
        )
        return f"{self._uri(blob_name)}?{sas}"

    async def close(self) -> None:
        """Release the underlying SDK client + credential. Call on shutdown."""
        await self._service.close()
        close = getattr(self._credential, "close", None)
        if close is not None:
            await close()


__all__ = [
    "AzureStorageClient",
    "STREAMING_THRESHOLD_BYTES",
    # ContainerSasPermissions re-exported for type hints by callers; harmless
    "ContainerSasPermissions",
]
