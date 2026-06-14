"""JWT issuance for access tokens.

The payload shape produced here MUST be acceptable to
``shared.auth.jwt_validator.decode_token``, which enforces:

* algorithm = HS256
* claims exactly {sub, role, exp, iat, iss, jti, scope} — no extras
  (because ``TokenPayload`` is ``extra="forbid"``)
* ``iat`` not in the future (with a small skew tolerance)
* ``iss`` matches the configured issuer

If a future change to the validator adds or renames a claim, this module
MUST be updated in lockstep — the JWT contract is the single most
critical interop point between services.

Environment variables consumed (read at issuance time so test fixtures
that monkeypatch them work correctly):

* ``JWT_SECRET`` — required. Module raises ``RuntimeError`` if missing.
* ``JWT_ISSUER`` — defaults to ``"maisys"`` (per Clarifications Log C5).
* ``ACCESS_TOKEN_EXPIRE_MINUTES`` — defaults to 30 (per
  Clarifications Log C7).
"""

from __future__ import annotations

import os
import time
import uuid

from jose import jwt

from shared.auth import Role


def issue_access_token(
    user_id: str,
    role: Role,
    scope: list[str] | None = None,
) -> tuple[str, str]:
    """Sign and return ``(token, jti)``.

    The caller persists the ``jti`` in the ``sessions`` table alongside
    the refresh token hash so the access token can be revoked
    server-side by deleting/revoking that session row.
    """
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET environment variable is not set; refusing to sign")
    issuer = os.environ.get("JWT_ISSUER", "maisys")
    expire_minutes_str = os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
    try:
        expire_minutes = int(expire_minutes_str)
    except ValueError as e:
        raise RuntimeError(
            f"ACCESS_TOKEN_EXPIRE_MINUTES must be an integer; got {expire_minutes_str!r}"
        ) from e

    now = int(time.time())
    jti = str(uuid.uuid4())
    payload: dict[str, object] = {
        "sub": str(user_id),
        "role": role.value,
        "exp": now + expire_minutes * 60,
        "iat": now,
        "iss": issuer,
        "jti": jti,
        "scope": scope if scope is not None else [],
    }
    token = jwt.encode(payload, secret, algorithm="HS256")
    return token, jti


__all__ = ["issue_access_token"]
