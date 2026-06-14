"""auth-service-specific exceptions, extending shared error_handler bases.

These types let routes raise expressive, code-tagged errors that the
shared exception handler translates into the standard MAISYS error
envelope. Every exception here sets:

* ``code`` — a stable machine-readable identifier (UPPER_SNAKE)
* ``status_code`` — the HTTP status the exception handler returns

Routes raise these; services raise these; the shared handler in
``shared.error_handler.handler`` converts them to the JSON envelope and
the right HTTP status. Tests assert on ``code`` / ``status_code`` rather
than on string messages — message phrasing may change with i18n; codes
are the contract.
"""

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
