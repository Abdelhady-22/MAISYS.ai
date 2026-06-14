"""Text normalisation for Arabic + English emergency-pattern matching.

Per Part 5 §5.1, input is normalised before regex matching:

* lowercase
* remove diacritics (harakat)
* normalise Arabic hamza forms (أ, إ, آ → ا)
* normalise alif maqsura (ى → ي)
* normalise ta marbuta (ة → ه) — controversial, see note below
* collapse whitespace

The ta-marbuta normalisation is a deliberate widening — it folds
``مساعدة`` and ``مساعده`` to the same surface form. Many Arabic
speakers type colloquial spellings without the dotted form, and
medical phrases like ``ضربة قلب`` vs ``ضربه قلب`` should match
the same pattern. The downside is a slight loss of grammatical
specificity, which doesn't matter for keyword scanning.

This module is pure (no I/O) and synchronous — both endpoints call
it on every request and per Part 4 the latency budget is tight.
"""

from __future__ import annotations

import re
import unicodedata

# Arabic harakat (diacritics). All in U+064B..U+065F + tatweel U+0640.
_HARAKAT = re.compile(r"[\u064B-\u065F\u0670\u0640]")

# Multi-space → single space.
_WHITESPACE = re.compile(r"\s+")


def normalise_for_matching(text: str) -> str:
    """Return a normalised form of ``text`` suitable for keyword matching.

    The transformation is lossy by design — never use the output as
    storage or display text, only as a matching key.
    """
    if not text:
        return ""

    # Unicode NFC first — combines decomposed accents with their base
    # characters so the harakat regex above hits canonical forms.
    text = unicodedata.normalize("NFC", text)

    # Strip Arabic harakat / tatweel
    text = _HARAKAT.sub("", text)

    # Normalise hamza variants → bare alif
    _HAMZA_MAP: dict[str, str | int | None] = {
        "أ": "ا",  # alif with hamza above
        "إ": "ا",  # alif with hamza below
        "آ": "ا",  # alif with madda
        "ٱ": "ا",  # alif wasla
        "ى": "ي",  # alif maqsura → ya
        "ة": "ه",  # ta marbuta → ha (see note in module docstring)
        "ﻻ": "لا",  # presentation form ligature
    }
    text = text.translate(str.maketrans(_HAMZA_MAP))

    # Lowercase (English side)
    text = text.lower()

    # Collapse whitespace
    text = _WHITESPACE.sub(" ", text).strip()

    return text


__all__ = ["normalise_for_matching"]
