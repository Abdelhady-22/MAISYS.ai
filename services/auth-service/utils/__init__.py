"""Cryptographic and token-generation utilities for auth-service.

These are the only modules in the service that touch ``argon2``, ``jose``,
or the ``secrets``/``hashlib`` primitives. Routes and services consume the
high-level functions defined here and never re-implement the same
operations inline.
"""

from utils.jwt import issue_access_token
from utils.otp import generate_otp, hash_otp, verify_otp
from utils.password import hash_password, verify_password
from utils.tokens import generate_refresh_token, hash_refresh_token

__all__ = [
    "generate_otp",
    "generate_refresh_token",
    "hash_otp",
    "hash_password",
    "hash_refresh_token",
    "issue_access_token",
    "verify_otp",
    "verify_password",
]
