"""Canonical API response envelope used by every MAISYS service endpoint.

Every API endpoint in MAISYS returns an `APIResponse[T]`. Success looks like:

    APIResponse(success=True, data={...}, error=None, metadata={...})

Failure looks like:

    APIResponse(success=False, data=None, error=ErrorDetail(...), metadata={...})

Use the class methods `APIResponse.ok(data)` and
`APIResponse.error_from_exception(exc)` rather than constructing manually.
"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from shared.error_handler.exceptions import MaisysException

T = TypeVar("T")


class ErrorDetail(BaseModel):
    """Error payload inside APIResponse when success is False."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None


class APIResponse(BaseModel, Generic[T]):
    """Standard response envelope for every MAISYS API endpoint.

    Invariant: when `success=True`, `error` is None. When `success=False`,
    `error` is set and `data` is None.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    data: T | None = None
    error: ErrorDetail | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def ok(cls, data: T, metadata: dict[str, Any] | None = None) -> APIResponse[T]:
        """Construct a successful response."""
        return cls(success=True, data=data, error=None, metadata=metadata or {})

    @staticmethod
    def error_from_exception(exc: MaisysException) -> APIResponse[None]:
        """Construct an error response from a MaisysException.

        This is a staticmethod rather than classmethod because the resulting
        response is always APIResponse[None] regardless of the T the caller
        parameterized — there is no `data` payload on errors.
        """
        return APIResponse[None](
            success=False,
            data=None,
            error=ErrorDetail(
                code=exc.code,
                message=exc.message,
                details=exc.details,
                correlation_id=exc.correlation_id,
            ),
            metadata={},
        )
