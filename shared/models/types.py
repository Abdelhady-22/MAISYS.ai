"""Shared type aliases for cross-service consistency."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal, TypedDict

from pydantic import Field

# ─────────────────────────────────────────────────────────────────
# Language
# ─────────────────────────────────────────────────────────────────

ISOLanguageCode = Literal["ar", "en"]
"""ISO 639-1 codes for the languages MAISYS supports.

Add more by expanding the Literal. Every service that accepts a language
parameter should use this type for input validation."""


# ─────────────────────────────────────────────────────────────────
# Country (ISO 3166-1 alpha-2)
# ─────────────────────────────────────────────────────────────────

ISOCountryCode = Literal[
    # Middle East & North Africa
    "EG",  # Egypt
    "SA",  # Saudi Arabia
    "AE",  # United Arab Emirates
    "JO",  # Jordan
    "LB",  # Lebanon
    "PS",  # Palestine
    "SY",  # Syria
    "IQ",  # Iraq
    "KW",  # Kuwait
    "QA",  # Qatar
    "BH",  # Bahrain
    "OM",  # Oman
    "YE",  # Yemen
    "MA",  # Morocco
    "DZ",  # Algeria
    "TN",  # Tunisia
    "LY",  # Libya
    "SD",  # Sudan
    # Other commonly-needed
    "US",  # United States
    "GB",  # United Kingdom
    "CA",  # Canada
    "AU",  # Australia
    "DE",  # Germany
    "FR",  # France
    "IN",  # India
    "PK",  # Pakistan
    "TR",  # Turkey
]
"""ISO 3166-1 alpha-2 country codes for users of MAISYS.

Restricted intentionally — services that need a country code should accept
this Literal so unknown values are rejected at the API boundary. Expand the
list (and ship a migration to update existing data) when new markets open up.
"""


# ─────────────────────────────────────────────────────────────────
# Bilingual text
# ─────────────────────────────────────────────────────────────────


class BilingualText(TypedDict):
    """Text with both Arabic and English versions, both required.

    Used wherever content must be available in both MAISYS languages —
    medical glossary terms, system notifications, error messages shown to
    users (vs. log messages, which stay English).
    """

    ar: str
    en: str


# ─────────────────────────────────────────────────────────────────
# Constrained numerics
# ─────────────────────────────────────────────────────────────────

PercentFloat = Annotated[float, Field(ge=0.0, le=1.0)]
"""Float in [0.0, 1.0] for ratios, probabilities, confidence scores.

Pydantic enforces the bounds on validation. Note this is NOT 0-100 — use
this for normalized values, format as percentage at the presentation layer."""


PositiveFloat = Annotated[float, Field(gt=0.0)]
"""Strictly positive float — e.g. dosages, durations in seconds, latencies."""


# ─────────────────────────────────────────────────────────────────
# Money
# ─────────────────────────────────────────────────────────────────


class Money(TypedDict):
    """Monetary amount with currency code.

    Use Decimal (not float) for amounts to avoid binary float precision
    issues. Currency is ISO 4217 3-letter code (e.g. "USD", "EGP", "EUR").
    """

    amount: Decimal
    currency: str
