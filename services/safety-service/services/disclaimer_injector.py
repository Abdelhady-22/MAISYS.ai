"""DisclaimerInjector — implements ``POST /safety/wrap``.

Per Part 5 §5.5, the calling service POSTs the response it was about
to return, plus the user's profile + drug names. We return:

* ``wrapped_content`` — the original content unchanged (the calling
  service is responsible for the medical text; we don't rewrite it)
* ``profile_warnings`` — a list of ``ProfileWarning`` objects the UI
  should surface alongside the content (pregnancy, pediatric, etc.)
* ``disclaimer_en`` / ``disclaimer_ar`` — the standard MAISYS
  educational-use disclaimer

The intent of the design is to keep this service simple: it never
modifies the wrapped content prose. Calling services get back a
warning list they can render however suits their UI — banners,
badges, expandable cards. This decouples safety policy from
presentation.

Pregnancy rules are evaluated only when ``user_profile.is_pregnant``
is True AND the context is drug-related (``drug_profile`` /
``drug_interaction`` / ``drug_dosage``). For non-drug contexts, drug
names in ``drug_names`` are ignored — a chatbot answer that
mentions ibuprofen in passing shouldn't trigger a pregnancy banner.

Pediatric and chronic-condition warnings are scaffolded but return
an empty list in v1 — they're tracked in P3-C06 as follow-up work.
"""

from __future__ import annotations

from services.safety_service.exceptions.exceptions import InvalidSafetyInput
from services.safety_service.models.schemas import (
    Language,
    ProfileWarning,
    SafetyWrapRequest,
    SafetyWrapResponse,
    UserProfile,
    WrapContext,
)
from services.safety_service.services.pregnancy_rules import (
    get_pregnancy_warning_for,
)

DRUG_CONTEXTS: frozenset[WrapContext] = frozenset(
    {"drug_profile", "drug_interaction", "drug_dosage"}
)

DISCLAIMER_EN = (
    "This information is for educational purposes only and does not "
    "constitute medical advice. Always consult a qualified healthcare "
    "professional before making any health decisions."
)
DISCLAIMER_AR = (
    "هذه المعلومات لأغراض تعليمية فقط ولا تشكل نصيحة طبية. "
    "استشر دائماً أخصائياً صحياً مؤهلاً قبل اتخاذ أي قرارات صحية."
)


class DisclaimerInjector:
    """Builds the ``SafetyWrapResponse`` from a wrap request."""

    def wrap(self, request: SafetyWrapRequest) -> SafetyWrapResponse:
        self._validate_semantics(request.user_profile)

        warnings: list[ProfileWarning] = []
        warnings.extend(self._pregnancy_warnings(request))
        # Future hooks (P3-C06):
        # warnings.extend(self._pediatric_warnings(request))
        # warnings.extend(self._chronic_condition_warnings(request))

        return SafetyWrapResponse(
            wrapped_content=request.response_content,
            profile_warnings=warnings,
            disclaimer_en=DISCLAIMER_EN,
            disclaimer_ar=DISCLAIMER_AR,
        )

    # ─── Rule evaluation ──────────────────────────────────────────

    def _pregnancy_warnings(self, request: SafetyWrapRequest) -> list[ProfileWarning]:
        if not request.user_profile.is_pregnant:
            return []
        if request.context not in DRUG_CONTEXTS:
            return []
        out: list[ProfileWarning] = []
        seen: set[str] = set()
        for drug in request.drug_names:
            warning = get_pregnancy_warning_for(drug)
            if warning is None or warning.drug in seen:
                continue
            assert warning.drug is not None  # set by get_pregnancy_warning_for
            seen.add(warning.drug)
            out.append(warning)
        return out

    # ─── Semantic validation ──────────────────────────────────────

    @staticmethod
    def _validate_semantics(profile: UserProfile) -> None:
        if profile.pregnancy_trimester is not None and not profile.is_pregnant:
            raise InvalidSafetyInput(
                "user_profile.pregnancy_trimester is set but is_pregnant is False"
            )


def get_disclaimer(language: Language) -> str:
    """Return the standard educational disclaimer in the requested language."""
    return DISCLAIMER_AR if language == "ar" else DISCLAIMER_EN


__all__ = ["DRUG_CONTEXTS", "DisclaimerInjector", "get_disclaimer"]
