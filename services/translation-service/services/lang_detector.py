"""Language detection — deterministic, no external dependencies.

Per Part 1 §7.7 the service supports Arabic ↔ English only. Detection
is a count-based heuristic: if any Arabic Unicode characters appear,
the text is treated as Arabic; otherwise English.

This is more restrictive than what a general-purpose detector
(langdetect, fastText) would give, but it's predictable and avoids
shipping a 50MB model just to distinguish two languages. The cost is
a small failure mode: mixed-language text like "Take paracetamol مرتين
في اليوم" detects as Arabic because the Arabic range is matched
first. That's the right default — the meaningful clinical content is
in Arabic and translating to English is the typical caller need.
"""

from __future__ import annotations

import re

from services.translation_service.models.schemas import Language

# Arabic Unicode block + supplement + extended-A.
# U+0600..U+06FF — Arabic
# U+0750..U+077F — Arabic Supplement
# U+08A0..U+08FF — Arabic Extended-A
# U+FB50..U+FDFF — Arabic Presentation Forms-A
# U+FE70..U+FEFF — Arabic Presentation Forms-B
_ARABIC_PATTERN = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]")


def detect_language(text: str) -> Language:
    """Return ``'ar'`` if any Arabic character is present, else ``'en'``."""
    if _ARABIC_PATTERN.search(text):
        return "ar"
    return "en"


__all__ = ["detect_language"]
