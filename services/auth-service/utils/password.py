"""Password hashing with Argon2id.

Parameters follow OWASP's Password Storage Cheat Sheet recommendation for
Argon2id (2024 update): memory_cost=64 MiB, time_cost=3, parallelism=4.
These are the same parameters used by every other MAISYS service that
verifies user-provided passwords.

We use a single module-level ``PasswordHasher`` instance so the Argon2
configuration is set in exactly one place. Tests that need to exercise
edge cases (e.g. legacy hashes from another service) construct their own
``PasswordHasher`` and verify with that.

We do NOT use bcrypt anywhere in this codebase (per Clarifications Log
C10, PROGRESS.md). All password and OTP hashing goes through this module
(passwords) or ``utils.otp`` (OTPs, which use SHA-256 for schema-level
reasons documented there).
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

# Tuned per OWASP guidance for Argon2id, Jan 2024.
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=4,
)


def hash_password(password: str) -> str:
    """Hash a plaintext password into an Argon2id-encoded string.

    The returned value includes the algorithm identifier, parameters,
    salt, and digest — everything needed to verify later without storing
    parameters separately.
    """
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Return True if ``password`` matches ``password_hash``, else False.

    Argon2 raises on mismatch; we catch and return False so the caller
    sees a clean boolean and the timing of the comparison stays roughly
    constant (Argon2 itself runs the full KDF regardless).
    """
    if not isinstance(password, str) or not isinstance(password_hash, str):
        return False
    try:
        return bool(_HASHER.verify(password_hash, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


__all__ = ["hash_password", "verify_password"]
