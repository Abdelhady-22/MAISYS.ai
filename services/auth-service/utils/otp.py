"""One-Time Password (OTP) generation, hashing, and verification.

Lifecycle:
1. ``generate_otp()`` → fresh 6-digit code, sent to user via email
2. ``hash_otp(code)`` → stored in ``otp_codes.code_hash``
3. ``verify_otp(submitted, stored_hash)`` → constant-time comparison

Why SHA-256 (not Argon2 / bcrypt):
- The column is VARCHAR(64) per part5.md §1.1 (= SHA-256 hex length)
- OTPs are 6 digits = only 10^6 = 1M possibilities, but the lockout
  after 3 attempts (per Clarifications Log C9) limits brute-force to
  practically zero. Memory-hard hashing here would burn server CPU on
  every verify with no security benefit.

See PROGRESS.md Clarifications Log entry C10 for the full reasoning.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

OTP_LENGTH = 6
_MAX_OTP = 10**OTP_LENGTH  # 1,000,000


def generate_otp() -> str:
    """Generate a fresh 6-digit OTP, zero-padded.

    ``secrets.randbelow`` is cryptographically secure (built on OS
    entropy). Zero-padding ensures the returned string is always exactly
    6 characters — important because the schema validation in
    ``schemas.VerifyOTPRequest`` enforces ``min_length=6, max_length=6``.
    """
    code_int = secrets.randbelow(_MAX_OTP)
    return str(code_int).zfill(OTP_LENGTH)


def hash_otp(code: str) -> str:
    """SHA-256 hex of the OTP. Same digest a verify() will compare against."""
    if not isinstance(code, str):
        raise TypeError("code must be a string")
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def verify_otp(code: str, stored_hash: str) -> bool:
    """Constant-time comparison of hashed input against stored hash.

    Uses ``hmac.compare_digest`` (not ``==``) to avoid leaking timing
    information about how many leading hex characters of the digest
    matched. Both operands are passed through the same hash function so
    they're identically-sized strings.
    """
    if not isinstance(code, str) or not isinstance(stored_hash, str):
        return False
    candidate = hashlib.sha256(code.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate, stored_hash)


__all__ = ["OTP_LENGTH", "generate_otp", "hash_otp", "verify_otp"]
