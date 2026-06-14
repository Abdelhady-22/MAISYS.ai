"""Auth-service-specific exception classes.

Every class sets ``code`` and ``status_code`` as class attributes so a
plain ``raise EmailAlreadyExistsException("user@example.com already
registered")`` is enough — no need to repeat code/status at each raise
site. The constructor's kwargs (from ``MaisysException``) still allow
per-raise overrides for unusual cases.

The codes here become the wire-level error contract: every other service
or client UI that matches on auth errors will key on these strings.
"""

from __future__ import annotations

from shared.error_handler import (
    AuthenticationException,
    AuthorizationException,
    ConflictException,
    NotFoundException,
    ValidationException,
)


class EmailAlreadyExistsException(ConflictException):
    """A registration tried an email that's already in use."""

    code = "EMAIL_ALREADY_EXISTS"
    status_code = 409


class InvalidCredentialsException(AuthenticationException):
    """Login: wrong email or password.

    We intentionally use ONE code for both ``wrong email`` and ``wrong
    password`` so the response doesn't disclose which field was at fault
    — that prevents email enumeration.
    """

    code = "INVALID_CREDENTIALS"
    status_code = 401


class AccountLockedException(AuthenticationException):
    """Too many failed login attempts; the account is temporarily locked.

    Returns HTTP 423 (Locked) — RFC 4918's semantically correct status
    for "the resource is currently locked".
    """

    code = "ACCOUNT_LOCKED"
    status_code = 423


class EmailNotVerifiedException(AuthorizationException):
    """The user has not yet completed email verification."""

    code = "EMAIL_NOT_VERIFIED"
    status_code = 403


class AccountDeactivatedException(AuthorizationException):
    """The account exists but ``is_active`` is False (admin-disabled or
    self-deleted)."""

    code = "ACCOUNT_DEACTIVATED"
    status_code = 403


class OTPInvalidException(ValidationException):
    """The submitted OTP doesn't match the stored hash."""

    code = "OTP_INVALID"
    status_code = 400


class OTPExpiredException(ValidationException):
    """The OTP exists but its ``expires_at`` is in the past."""

    code = "OTP_EXPIRED"
    status_code = 400


class OTPMaxAttemptsException(AuthenticationException):
    """The OTP has been guessed wrongly 3 times (per Clarifications Log
    C9). The OTP is invalidated; the user must request a new one.

    Returns HTTP 429 (Too Many Requests) — semantically appropriate for
    a per-OTP rate-limit-like behaviour.
    """

    code = "OTP_MAX_ATTEMPTS"
    status_code = 429


class InvalidRefreshTokenException(AuthenticationException):
    """The submitted refresh token doesn't match any session (could be
    forged, already-rotated, or revoked)."""

    code = "INVALID_REFRESH_TOKEN"
    status_code = 401


class RefreshTokenExpiredException(AuthenticationException):
    """The refresh token's session row exists but ``expires_at`` has
    passed."""

    code = "REFRESH_TOKEN_EXPIRED"
    status_code = 401


class OAuthFailureException(AuthenticationException):
    """OAuth callback failed — invalid ID token, audience mismatch, or
    issuer not trusted."""

    code = "OAUTH_FAILURE"
    status_code = 401


class SessionNotFoundException(NotFoundException):
    """A session lookup (e.g. for ``DELETE /auth/sessions/{id}``) found no row."""

    code = "SESSION_NOT_FOUND"
    status_code = 404


class InvalidPasswordFormatException(ValidationException):
    """A password fails the MAISYS password rules.

    Most password validation happens in Pydantic schemas (which return
    422 with the structured error envelope). This exception is for the
    rare paths where service-layer code needs to reject a password
    outside the schema — for example, on a password-reset confirm where
    we want to log a structured audit event.
    """

    code = "INVALID_PASSWORD_FORMAT"
    status_code = 422


__all__ = [
    "AccountDeactivatedException",
    "AccountLockedException",
    "EmailAlreadyExistsException",
    "EmailNotVerifiedException",
    "InvalidCredentialsException",
    "InvalidPasswordFormatException",
    "InvalidRefreshTokenException",
    "OAuthFailureException",
    "OTPExpiredException",
    "OTPInvalidException",
    "OTPMaxAttemptsException",
    "RefreshTokenExpiredException",
    "SessionNotFoundException",
]
