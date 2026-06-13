"""Custom structlog processors for MAISYS.

scrub_sensitive: redacts values from the event dict where the key matches a
sensitive pattern, plus any string value that looks like a JWT. Runs as a
regular structlog processor in the configured chain.
"""

from __future__ import annotations

import re
from typing import Any, MutableMapping

REDACTED = "[REDACTED]"

# Substring/regex patterns on keys that indicate sensitive content.
# All match case-insensitively against the full key name.
_SENSITIVE_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"passwd", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"\btoken\b", re.IGNORECASE),
    re.compile(r"access[_-]?token", re.IGNORECASE),
    re.compile(r"refresh[_-]?token", re.IGNORECASE),
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
    re.compile(r"\bcookie\b", re.IGNORECASE),
    re.compile(r"set[_-]?cookie", re.IGNORECASE),
    re.compile(r"private[_-]?key", re.IGNORECASE),
    re.compile(r"client[_-]?secret", re.IGNORECASE),
)

# Conservative JWT detector. Three base64url segments separated by dots,
# where the header (first segment) starts with "ey" (the {"alg":... start
# encoded). This catches real JWTs without matching arbitrary text.
_JWT_PATTERN: re.Pattern[str] = re.compile(
    r"^ey[A-Za-z0-9_-]{4,}\.ey[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}$"
)


def scrub_sensitive(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor that redacts sensitive values from the event dict.

    Redacts:
    - Any value whose key matches a sensitive pattern (password, secret, token,
      api_key, authorization, cookie, set_cookie, private_key, client_secret,
      access_token, refresh_token) — case-insensitive.
    - Any string value that looks like a JWT (ey...3-segment-base64url).

    The key is preserved; only the value is replaced with "[REDACTED]". This
    makes it visible in logs that the field WAS present, which is useful for
    debugging.
    """
    for key in list(event_dict.keys()):
        if _is_sensitive_key(key):
            event_dict[key] = REDACTED
            continue

        value = event_dict[key]
        if isinstance(value, str) and _JWT_PATTERN.match(value):
            event_dict[key] = REDACTED

    return event_dict


def _is_sensitive_key(key: str) -> bool:
    return any(p.search(key) for p in _SENSITIVE_KEY_PATTERNS)
