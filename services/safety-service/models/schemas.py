"""Pydantic schemas for safety-service.

Models mirror Part 5 §5.3 (emergency response payload) and §5.5 (API
contracts) exactly. The service is bilingual: every user-visible
string field comes as ``_en`` / ``_ar`` pairs so the calling service
can show the appropriate language without re-translating.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["en", "ar"]
"""Two-letter ISO language code. Only English and Arabic are supported."""

Severity = Literal["critical", "high", "moderate", "low", "info"]
"""Used in ``ProfileWarning.severity`` and ``SafetyCheckResponse.severity``.
The high end is for life-threatening events; ``info`` is purely
educational."""

EmergencyCategory = Literal[
    "cardiac",
    "respiratory",
    "stroke",
    "bleeding",
    "allergic",
    "mental_health_crisis",
    "pediatric_emergency",
    "obstetric_emergency",
    "overdose",
    "trauma",
    "seizure",
    "loss_of_consciousness",
    "abdominal",
    "head_injury",
    "ingestion",
    "unspecified",
]
"""Coarse categorisation of the emergency. Drives the response
template selection. ``unspecified`` is used when the pattern matched
something emergency-shaped but didn't fit a known bucket."""

WrapContext = Literal[
    "drug_profile",
    "drug_interaction",
    "drug_dosage",
    "lab_interpretation",
    "symptom_triage",
    "chatbot_response",
    "research_qa",
    "generic",
]


# ─── /safety/check request + response ────────────────────────────


class SafetyCheckRequest(BaseModel):
    """Body of ``POST /safety/check``."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    """User-supplied free text to scan for emergency indicators."""

    language: Language = "en"
    """Language hint. The detector runs both English and Arabic
    patterns regardless, but ``language`` selects which template the
    response payload uses for ``title``/``message``/``actions``."""

    session_id: str | None = None
    """Optional session id propagated into the audit log. The service
    itself is stateless, so this is recorded in structured logs only."""


class EmergencyResponse(BaseModel):
    """Bilingual emergency-response payload (Part 5 §5.3)."""

    model_config = ConfigDict(extra="forbid")

    title_en: str
    title_ar: str
    message_en: str
    message_ar: str
    actions_en: list[str] = Field(default_factory=list)
    actions_ar: list[str] = Field(default_factory=list)
    do_not_wait: bool = True
    """When true the calling UI is expected to surface the alert
    immediately and block the user from continuing the original flow.
    Set false for advisory-only situations (none currently)."""

    session_should_halt: bool = True
    """When true the calling service halts normal processing for this
    request and returns only the emergency payload."""


class SafetyCheckResponse(BaseModel):
    """Body returned by ``POST /safety/check``.

    Two shapes:

    * Safe input → ``{"is_emergency": false}``; all other fields null.
    * Emergency → ``is_emergency=True`` plus ``severity``,
      ``detected_pattern``, ``category`` and the full bilingual
      ``emergency_response`` payload.
    """

    model_config = ConfigDict(extra="forbid")

    is_emergency: bool
    severity: Severity | None = None
    detected_pattern: str | None = None
    """A short stable identifier for the matched pattern (e.g.
    ``"chest_pain"``). For LLM-confirmed cases this is the pattern
    that originally tripped Stage 1.5."""

    category: EmergencyCategory | None = None
    detection_stage: Literal["stage_1", "stage_2_llm"] | None = None
    """Which stage produced the verdict — Stage 1 fast pattern match
    or Stage 2 LLM confirmation. Useful for offline accuracy review."""

    emergency_response: EmergencyResponse | None = None


# ─── /safety/wrap request + response ──────────────────────────────


class UserProfile(BaseModel):
    """Subset of the user's health profile relevant to safety wrapping."""

    model_config = ConfigDict(extra="forbid")

    age_years: int | None = Field(default=None, ge=0, le=120)
    is_pregnant: bool | None = None
    pregnancy_trimester: Literal[1, 2, 3] | None = None
    chronic_conditions: list[str] = Field(default_factory=list)
    """Lowercased condition names (e.g. ``["hypertension", "asthma"]``)."""


class SafetyWrapRequest(BaseModel):
    """Body of ``POST /safety/wrap``."""

    model_config = ConfigDict(extra="forbid")

    response_content: str = Field(min_length=1, max_length=20_000)
    """The text the calling service was about to return to the user."""

    language: Language = "en"

    user_profile: UserProfile = Field(default_factory=UserProfile)

    context: WrapContext = "generic"
    """What kind of response is being wrapped. Determines which
    warning rules apply (e.g. pregnancy + drug warnings only fire on
    ``drug_*`` contexts)."""

    drug_names: list[str] = Field(default_factory=list)
    """Lowercased generic drug names mentioned in the response. The
    caller is responsible for normalising these — safety-service does
    not run RxNorm itself."""


class ProfileWarning(BaseModel):
    """A single profile-derived advisory attached to a wrapped response."""

    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "pregnancy_warning",
        "pediatric_warning",
        "elderly_warning",
        "chronic_condition_warning",
    ]
    severity: Severity
    message_en: str
    message_ar: str
    drug: str | None = None
    """The drug this warning is about, when applicable."""


class SafetyWrapResponse(BaseModel):
    """Body returned by ``POST /safety/wrap``."""

    model_config = ConfigDict(extra="forbid")

    wrapped_content: str
    """The original ``response_content`` unchanged. Calling services
    can present this verbatim — ``profile_warnings`` are listed
    separately so the UI can render them as banners/badges rather
    than splicing them into prose."""

    profile_warnings: list[ProfileWarning] = Field(default_factory=list)
    disclaimer_en: str
    disclaimer_ar: str


# ─── shared envelope (mirrors shared/error_handler.APIResponse shape)


class APIResponse(BaseModel):
    """Outer envelope returned by every endpoint.

    Mirrors ``shared.error_handler.APIResponse``. We redeclare it here
    so this service's OpenAPI spec is self-contained even when shared
    moves; the shape is intentionally identical.
    """

    model_config = ConfigDict(extra="forbid")

    success: bool
    data: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


__all__ = [
    "APIResponse",
    "EmergencyCategory",
    "EmergencyResponse",
    "Language",
    "ProfileWarning",
    "SafetyCheckRequest",
    "SafetyCheckResponse",
    "SafetyWrapRequest",
    "SafetyWrapResponse",
    "Severity",
    "UserProfile",
    "WrapContext",
]
