"""Tests for the language detector."""

from __future__ import annotations

import pytest

from services.translation_service.services.lang_detector import detect_language


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Hello world", "en"),
        ("Take paracetamol twice daily", "en"),
        ("How are you?", "en"),
        ("مرحبا بك", "ar"),
        ("عندي صداع شديد", "ar"),
        ("خذ الدواء مرتين", "ar"),
        # Mixed text — Arabic wins because it appears
        ("Take paracetamol مرتين", "ar"),
        # Empty → English default
        ("", "en"),
        # Numbers and punctuation only → English
        ("123 456.78", "en"),
    ],
)
def test_detect_language(text: str, expected: str) -> None:
    assert detect_language(text) == expected
