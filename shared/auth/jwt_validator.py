"""JWT decoding and validation.

`decode_token` is the single entry point. It verifies the HS256 signature,
expiration, issuer, and a custom "iat not in the future" check (python-jose
doesn't validate iat against wall clock by default), then parses the claims
into a TokenPayload.

Every failure raises AuthenticationException with a stable code so callers
can branch on the failure mode.
"""

from __future__ import annotations

import time

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError, JWTClaimsError
from pydantic import ValidationError

from shared.auth.types import TokenPayload
from shared.error_handler import AuthenticationException

# Tolerance for slight clock skew between issuer (auth-service) and validator
# (other services). 5 seconds covers reasonable NTP drift; larger windows are
# a security liability (replay attacks).
_IAT_SKEW_SECONDS = 5


def decode_token(token: str, secret: str, issuer: str = "maisys") -> TokenPayload:
    """Verify and decode a MAISYS-issued JWT.

    Args:
        token: the encoded JWT string (no "Bearer " prefix)
        secret: the shared HS256 secret
        issuer: expected `iss` claim value

    Returns:
        TokenPayload — the validated claims.

    Raises:
        AuthenticationException with code in:
            TOKEN_EXPIRED, TOKEN_INVALID_SIGNATURE, TOKEN_INVALID_ISSUER,
            TOKEN_FUTURE_IAT, TOKEN_MALFORMED
    """
    try:
        raw_claims = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            # We do not use the `aud` claim in MAISYS tokens
            options={"verify_aud": False},
        )
    except ExpiredSignatureError as e:
        raise AuthenticationException("Token has expired", code="TOKEN_EXPIRED", cause=e) from e
    except JWTClaimsError as e:
        # python-jose raises this for issuer mismatch and other claim-level
        # mismatches that aren't signature/encoding errors.
        raise AuthenticationException(
            "Token issuer is invalid",
            code="TOKEN_INVALID_ISSUER",
            cause=e,
        ) from e
    except JWTError as e:
        # Catches signature mismatch, malformed JWT, unsupported alg, etc.
        raise AuthenticationException(
            "Token signature is invalid",
            code="TOKEN_INVALID_SIGNATURE",
            cause=e,
        ) from e

    # python-jose does not validate iat against wall clock — do it ourselves.
    iat = raw_claims.get("iat")
    if isinstance(iat, int) and iat > int(time.time()) + _IAT_SKEW_SECONDS:
        raise AuthenticationException(
            "Token issued-at time is in the future",
            code="TOKEN_FUTURE_IAT",
        )

    try:
        return TokenPayload(**raw_claims)
    except ValidationError as e:
        # Token decoded and signed correctly but doesn't match the expected
        # claim shape — auth-service is broken or someone is forging tokens
        # with the right secret but wrong shape.
        raise AuthenticationException(
            "Token claims are malformed",
            code="TOKEN_MALFORMED",
            details={"errors": e.errors()},
            cause=e,
        ) from e
