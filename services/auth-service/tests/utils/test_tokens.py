"""Tests for utils.tokens (refresh-token generation and hashing)."""

from __future__ import annotations

import hashlib
import re

import pytest

from utils.tokens import generate_refresh_token, hash_refresh_token


def test_generate_refresh_token_is_url_safe() -> None:
    """Output must contain only URL-safe base64 characters."""
    t = generate_refresh_token()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", t), f"non-url-safe chars in {t!r}"


def test_generate_refresh_token_has_expected_entropy() -> None:
    """32 random bytes → 43 chars URL-safe base64 (no padding)."""
    t = generate_refresh_token()
    assert len(t) == 43


def test_generate_refresh_token_unique_each_call() -> None:
    """A fresh call must produce a fresh token (statistical near-certainty)."""
    samples = {generate_refresh_token() for _ in range(100)}
    assert len(samples) == 100


def test_hash_refresh_token_matches_sha256() -> None:
    """The hash function must be plain SHA-256 hex of utf-8 bytes."""
    t = "test-refresh-token-payload"
    expected = hashlib.sha256(t.encode("utf-8")).hexdigest()
    assert hash_refresh_token(t) == expected


def test_hash_refresh_token_deterministic() -> None:
    """Same input → same hash, every call."""
    t = "stable-input-12345"
    assert hash_refresh_token(t) == hash_refresh_token(t)


def test_hash_length_is_64_hex_chars() -> None:
    """SHA-256 hex is always 64 chars — matches the column VARCHAR(64)."""
    h = hash_refresh_token("any-input")
    assert len(h) == 64
    assert re.fullmatch(r"[0-9a-f]+", h)


def test_hash_refresh_token_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        hash_refresh_token(12345)  # type: ignore[arg-type]
