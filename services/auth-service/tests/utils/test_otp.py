"""Tests for utils.otp (6-digit OTP generation and verification)."""

from __future__ import annotations

import re

import pytest

from utils.otp import OTP_LENGTH, generate_otp, hash_otp, verify_otp


def test_generate_otp_always_6_digits() -> None:
    """OTP must always be exactly 6 digits, zero-padded."""
    for _ in range(200):
        otp = generate_otp()
        assert re.fullmatch(r"\d{6}", otp), f"got {otp!r}"
        assert len(otp) == OTP_LENGTH


def test_generate_otp_distribution_includes_low_numbers() -> None:
    """Zero-padding must work — values like '000042' should be reachable.

    Statistically, in 5000 samples we should see at least one OTP starting
    with '0' (≈10% probability per draw → vanishing chance of missing it
    in 5000 tries).
    """
    saw_leading_zero = False
    for _ in range(5000):
        if generate_otp().startswith("0"):
            saw_leading_zero = True
            break
    assert saw_leading_zero, "no leading-zero OTPs in 5000 draws — distribution broken?"


def test_hash_otp_is_sha256_hex() -> None:
    """Hash output is 64-char hex (SHA-256)."""
    h = hash_otp("123456")
    assert len(h) == 64
    assert re.fullmatch(r"[0-9a-f]+", h)


def test_verify_otp_accepts_correct_code() -> None:
    code = "654321"
    stored = hash_otp(code)
    assert verify_otp(code, stored) is True


def test_verify_otp_rejects_wrong_code() -> None:
    stored = hash_otp("111111")
    assert verify_otp("222222", stored) is False


def test_verify_otp_rejects_non_string() -> None:
    """Wrong types return False instead of raising — defensive coding."""
    assert verify_otp(123456, "anything") is False  # type: ignore[arg-type]
    assert verify_otp("123456", None) is False  # type: ignore[arg-type]


def test_hash_otp_rejects_non_string() -> None:
    with pytest.raises(TypeError):
        hash_otp(123456)  # type: ignore[arg-type]
