"""Tests for auth-service-specific exceptions.

We verify three things per exception:
1. ``code`` matches the expected string (the wire contract)
2. ``status_code`` matches the expected HTTP status
3. The exception is a subclass of ``MaisysException`` (so the shared
   error handler picks it up via isinstance check)
"""

from __future__ import annotations

import pytest

from shared.error_handler import (
    AuthenticationException,
    AuthorizationException,
    ConflictException,
    MaisysException,
    NotFoundException,
    ValidationException,
)

from exceptions.auth_exceptions import (
    AccountDeactivatedException,
    AccountLockedException,
    EmailAlreadyExistsException,
    EmailNotVerifiedException,
    InvalidCredentialsException,
    InvalidPasswordFormatException,
    InvalidRefreshTokenException,
    OAuthFailureException,
    OTPExpiredException,
    OTPInvalidException,
    OTPMaxAttemptsException,
    RefreshTokenExpiredException,
    SessionNotFoundException,
)

# (class, expected_code, expected_status, parent_class)
_CASES = [
    (EmailAlreadyExistsException, "EMAIL_ALREADY_EXISTS", 409, ConflictException),
    (InvalidCredentialsException, "INVALID_CREDENTIALS", 401, AuthenticationException),
    (AccountLockedException, "ACCOUNT_LOCKED", 423, AuthenticationException),
    (EmailNotVerifiedException, "EMAIL_NOT_VERIFIED", 403, AuthorizationException),
    (AccountDeactivatedException, "ACCOUNT_DEACTIVATED", 403, AuthorizationException),
    (OTPInvalidException, "OTP_INVALID", 400, ValidationException),
    (OTPExpiredException, "OTP_EXPIRED", 400, ValidationException),
    (OTPMaxAttemptsException, "OTP_MAX_ATTEMPTS", 429, AuthenticationException),
    (InvalidRefreshTokenException, "INVALID_REFRESH_TOKEN", 401, AuthenticationException),
    (RefreshTokenExpiredException, "REFRESH_TOKEN_EXPIRED", 401, AuthenticationException),
    (OAuthFailureException, "OAUTH_FAILURE", 401, AuthenticationException),
    (SessionNotFoundException, "SESSION_NOT_FOUND", 404, NotFoundException),
    (InvalidPasswordFormatException, "INVALID_PASSWORD_FORMAT", 422, ValidationException),
]


@pytest.mark.parametrize(
    ("exc_class", "expected_code", "expected_status", "expected_parent"),
    _CASES,
)
def test_exception_attributes_and_inheritance(
    exc_class: type[MaisysException],
    expected_code: str,
    expected_status: int,
    expected_parent: type,
) -> None:
    # Class-level attributes (set without instantiation)
    assert exc_class.code == expected_code
    assert exc_class.status_code == expected_status

    # Inheritance: every exception eventually inherits from MaisysException
    # via the appropriate shared base class.
    assert issubclass(exc_class, expected_parent)
    assert issubclass(exc_class, MaisysException)

    # Instance keeps the class-level values
    instance = exc_class("test message")
    assert instance.code == expected_code
    assert instance.status_code == expected_status
    assert instance.message == "test message"


def test_exception_supports_kwarg_overrides() -> None:
    """The MaisysException base allows per-raise overrides via kwargs."""
    exc = EmailAlreadyExistsException(
        "email exists",
        details={"email_hash": "abc123"},
        correlation_id="req-42",
    )
    assert exc.details == {"email_hash": "abc123"}
    assert exc.correlation_id == "req-42"
    # Class defaults still apply unless overridden
    assert exc.code == "EMAIL_ALREADY_EXISTS"
    assert exc.status_code == 409


def test_exception_can_be_raised_and_caught_polymorphically() -> None:
    """A handler can catch ``MaisysException`` and route by ``code``."""
    try:
        raise OTPMaxAttemptsException("locked out")
    except MaisysException as exc:
        assert exc.code == "OTP_MAX_ATTEMPTS"
        assert exc.status_code == 429
