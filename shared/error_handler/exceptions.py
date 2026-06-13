"""Exception hierarchy for MAISYS services.

All MAISYS service-side errors should be raised as one of these exceptions.
The FastAPI handler (setup_exception_handlers) translates them to APIResponse
JSON envelopes with the correct HTTP status code.

Conventions:
- `code` is a short stable identifier consumers can branch on (e.g.
  "VALIDATION_FAILED"). Service code can override the default code via the
  constructor when more granularity is useful (e.g. "EMAIL_INVALID").
- `status_code` is the HTTP status the handler will return.
- `details` carries arbitrary structured context. Pydantic-friendly types only
  (must be JSON-serializable).
- `correlation_id` is normally left None at raise time; the global handler
  fills it in from request.state.request_id.
"""

from __future__ import annotations

from typing import Any


class MaisysException(Exception):
    """Base exception for all MAISYS service errors.

    Subclasses set sensible defaults for `code` and `status_code` as class
    attributes. Per-raise overrides are accepted via constructor kwargs.
    """

    code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(
        self,
        message: str = "An internal error occurred",
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details: dict[str, Any] = details or {}
        self.correlation_id: str | None = correlation_id
        self.cause: BaseException | None = cause


class ValidationException(MaisysException):
    """Client-side validation failure (400)."""

    code = "VALIDATION_FAILED"
    status_code = 400


class AuthenticationException(MaisysException):
    """Authentication failure: missing, invalid, or expired credentials (401)."""

    code = "AUTHENTICATION_FAILED"
    status_code = 401


class AuthorizationException(MaisysException):
    """Authorization failure: authenticated but not permitted (403)."""

    code = "AUTHORIZATION_FAILED"
    status_code = 403


class NotFoundException(MaisysException):
    """Requested resource does not exist (404)."""

    code = "NOT_FOUND"
    status_code = 404


class ConflictException(MaisysException):
    """Resource conflict: duplicate, version mismatch, etc. (409)."""

    code = "CONFLICT"
    status_code = 409


class RateLimitException(MaisysException):
    """Rate limit exceeded (429)."""

    code = "RATE_LIMITED"
    status_code = 429


class ExternalServiceException(MaisysException):
    """An upstream/external dependency failed (502)."""

    code = "EXTERNAL_SERVICE_ERROR"
    status_code = 502


class MedicalSafetyException(MaisysException):
    """Content blocked by the medical safety layer (451).

    HTTP 451 ("Unavailable For Legal Reasons") is the closest semantic match
    for safety-blocked content in standard HTTP status codes.
    """

    code = "MEDICAL_SAFETY_BLOCKED"
    status_code = 451
