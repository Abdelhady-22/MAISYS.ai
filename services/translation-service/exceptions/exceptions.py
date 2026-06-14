"""translation-service exception classes."""

from __future__ import annotations

from shared.error_handler import MaisysException


class TranslationServiceException(MaisysException):
    """Base for every translation-service error."""

    code = "TRANSLATION_SERVICE_ERROR"
    status_code = 500


class TranslationFailed(TranslationServiceException):
    """The underlying translation provider rejected the request or errored."""

    code = "TRANSLATION_FAILED"
    status_code = 502


class TranslationModeUnavailable(TranslationServiceException):
    """The requested mode isn't configured (missing API key, missing SDK).

    Returned as 503 so caller can retry against a different mode or
    surface the configuration gap.
    """

    code = "TRANSLATION_MODE_UNAVAILABLE"
    status_code = 503


class UnsupportedLanguagePair(TranslationServiceException):
    """Caller asked for a language pair we don't support."""

    code = "UNSUPPORTED_LANGUAGE_PAIR"
    status_code = 400


__all__ = [
    "TranslationFailed",
    "TranslationModeUnavailable",
    "TranslationServiceException",
    "UnsupportedLanguagePair",
]
