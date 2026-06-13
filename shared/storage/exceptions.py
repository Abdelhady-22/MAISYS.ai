"""Storage exception hierarchy.

Every backend translates its native cloud-SDK errors into one of these four
exceptions so service code never has to know which cloud it's running
against. The hierarchy plugs into ``shared.error_handler``:

    MaisysException
    └── ExternalServiceException        (502 by default)
        └── StorageException            (generic storage failure)
            ├── ObjectNotFoundException (404)
            ├── AccessDeniedException   (403)
            └── ChecksumMismatchException (502; upstream returned bad data)

Use the most specific subclass available. ``StorageException`` is the
catch-all for unexpected backend failures (network errors, malformed
responses, etc.).
"""

from __future__ import annotations

from shared.error_handler import ExternalServiceException


class StorageException(ExternalServiceException):
    """Generic storage failure. Use a more specific subclass when possible."""

    code = "STORAGE_ERROR"
    # status_code inherited (502)


class ObjectNotFoundException(StorageException):
    """Requested object does not exist in the backend (HTTP 404 / equivalent)."""

    code = "STORAGE_NOT_FOUND"
    status_code = 404


class AccessDeniedException(StorageException):
    """Backend denied access to the object (HTTP 403 / equivalent)."""

    code = "STORAGE_ACCESS_DENIED"
    status_code = 403


class ChecksumMismatchException(StorageException):
    """Post-write verification found the stored bytes don't match the source.

    Surfaced when a backend exposes a server-computed hash that doesn't
    agree with the local hash of the bytes we sent. Indicates either
    network corruption or a bug.
    """

    code = "STORAGE_CHECKSUM_MISMATCH"
    # status_code inherited (502)
