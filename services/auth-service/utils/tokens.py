"""Refresh-token generation and hashing.

Refresh tokens are opaque random strings — NOT JWTs. They live as a
SHA-256 hash in the ``sessions`` table; the raw token only exists in the
HTTP response that delivered it to the client and is never stored.

Why opaque tokens rather than JWTs:
* Revocation is trivial — delete the session row.
* No claim parsing required server-side, so the validation path is one
  hash + one indexed lookup.
* Smaller than equivalent JWTs.

Length: 32 random bytes → 43 characters of URL-safe base64 (no padding).
``secrets.token_urlsafe`` provides cryptographically secure randomness.
"""

from __future__ import annotations

import hashlib
import secrets

# 32 bytes = 256 bits of entropy, far more than required for an opaque
# token. The encoded form is 43 chars (URL-safe base64, no padding).
_TOKEN_BYTES = 32


def generate_refresh_token() -> str:
    """Return a fresh, URL-safe refresh token string.

    Uses ``secrets.token_urlsafe`` which is built on the OS entropy
    source. Output contains only [A-Za-z0-9_-].
    """
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_refresh_token(token: str) -> str:
    """SHA-256 hex digest of a refresh token.

    SHA-256 (not Argon2) is correct here: refresh tokens have full 256
    bits of entropy so they're not vulnerable to brute-force the way a
    user password would be. Argon2's memory-hardness adds no security
    and a lot of latency on every refresh request.
    """
    if not isinstance(token, str):
        raise TypeError("token must be a string")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


__all__ = ["generate_refresh_token", "hash_refresh_token"]
