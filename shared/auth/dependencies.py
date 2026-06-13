"""FastAPI dependencies for retrieving the authenticated user.

Both dependencies read the JWT secret and issuer from environment variables
at request time. Reading per-request (rather than module load time) means
hot-reloading tests can set env vars in setup; it has no production cost
since os.environ lookups are cheap.

JWT_SECRET (required) — the HS256 shared secret. In production this is
injected from cloud Secret Manager into the service's environment.

JWT_ISSUER (optional, default "maisys") — the expected `iss` claim value.
"""

from __future__ import annotations

import os

from fastapi import Header

from shared.auth.jwt_validator import decode_token
from shared.auth.types import TokenPayload
from shared.error_handler import AuthenticationException

_BEARER_PREFIX = "Bearer "


def _get_jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        # Missing JWT_SECRET is a configuration error, not an auth failure.
        # Raise a plain RuntimeError so the global exception handler returns
        # a generic 500 (we don't want to leak "JWT_SECRET unset" to the
        # client — that's an internal config bug).
        raise RuntimeError(
            "JWT_SECRET environment variable is not set. Configure it via "
            "the service's secret manager binding before starting."
        )
    return secret


def _get_jwt_issuer() -> str:
    return os.environ.get("JWT_ISSUER", "maisys")


def _parse_bearer(authorization: str) -> str:
    """Extract the token from an Authorization header value."""
    if not authorization.startswith(_BEARER_PREFIX):
        raise AuthenticationException(
            "Authorization header must use Bearer scheme",
            code="AUTH_HEADER_INVALID",
        )
    token = authorization[len(_BEARER_PREFIX) :].strip()
    if not token:
        raise AuthenticationException(
            "Authorization header has no token",
            code="AUTH_HEADER_INVALID",
        )
    return token


async def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> TokenPayload:
    """FastAPI dependency that returns the authenticated TokenPayload.

    Raises AuthenticationException (which the global exception handler
    converts to a 401 APIResponse envelope) when:
    - The Authorization header is missing
    - The header doesn't use the Bearer scheme
    - The token is invalid (expired, wrong signature, etc.)
    """
    if authorization is None:
        raise AuthenticationException(
            "Authorization header is required",
            code="AUTH_HEADER_MISSING",
        )
    token = _parse_bearer(authorization)
    return decode_token(token, _get_jwt_secret(), _get_jwt_issuer())


async def get_current_user_optional(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> TokenPayload | None:
    """FastAPI dependency that returns the authenticated user or None.

    Returns None when no Authorization header is present (anonymous request).
    Still raises AuthenticationException when a header is present but invalid
    — never silently treat a bad token as anonymous, because that would let
    expired tokens bypass auth on routes that gracefully degrade.
    """
    if authorization is None:
        return None
    token = _parse_bearer(authorization)
    return decode_token(token, _get_jwt_secret(), _get_jwt_issuer())
