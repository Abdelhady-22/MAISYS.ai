"""Service-specific exception classes.

Every safety-service exception extends ``MaisysException`` from
``shared.error_handler`` so the global handler in ``main.py`` can map
them to consistent HTTP responses. Each exception carries:

* ``code`` — short stable string the client switches on
* ``status_code`` — HTTP code the global handler returns
* ``message`` — human-readable, language-neutral (en)

The global ``APIResponse`` envelope wraps these into the same
``{"success": false, "error": {...}}`` shape every MAISYS service
uses.
"""

from __future__ import annotations

from shared.error_handler import MaisysException


class SafetyServiceException(MaisysException):
    """Base for every safety-service error."""

    code = "SAFETY_SERVICE_ERROR"
    status_code = 500


class SafetyLLMTimeout(SafetyServiceException):
    """Stage 2 LLM confirmation didn't return within the configured timeout."""

    code = "SAFETY_LLM_TIMEOUT"
    status_code = 504


class InvalidSafetyInput(SafetyServiceException):
    """Input was syntactically valid (passed Pydantic) but semantically wrong.

    Example: ``user_profile.pregnancy_trimester`` set when
    ``is_pregnant`` is false. We use Pydantic for shape and this for
    cross-field semantic rules so the route layer stays thin.
    """

    code = "INVALID_SAFETY_INPUT"
    status_code = 400


__all__ = [
    "InvalidSafetyInput",
    "SafetyLLMTimeout",
    "SafetyServiceException",
]
