"""Tests for utils.password (Argon2id wrapper)."""

from __future__ import annotations

from utils.password import hash_password, verify_password


def test_hash_password_returns_argon2id_encoded_string() -> None:
    """Hash output should be the standard Argon2 PHC string format."""
    h = hash_password("Correct-Horse-Battery-Staple-1")
    # All Argon2 hashes start with $argon2 — we tune the variant to id.
    assert h.startswith("$argon2id$")
    # The hash contains the parameters: m=memory_cost, t=time_cost, p=parallelism
    assert "m=65536" in h
    assert "t=3" in h
    assert "p=4" in h


def test_verify_password_accepts_correct_password() -> None:
    pw = "MySecretP@ssw0rd"
    h = hash_password(pw)
    assert verify_password(h, pw) is True


def test_verify_password_rejects_wrong_password() -> None:
    h = hash_password("right-password-1A")
    assert verify_password(h, "wrong-password-1A") is False


def test_verify_password_rejects_malformed_hash() -> None:
    """A malformed/corrupt hash returns False, not an exception."""
    assert verify_password("not-a-real-argon2-hash", "anything") is False


def test_hash_is_unique_per_call() -> None:
    """Argon2 salts each call, so the same plaintext hashes differently."""
    pw = "same-input-1A"
    assert hash_password(pw) != hash_password(pw)
    # Both still verify correctly
    assert verify_password(hash_password(pw), pw) is True
