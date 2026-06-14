"""Emergency keyword patterns — verbatim from Part 5 §5.2.

The lists are split into two tiers:

* **Stage 1 (clear)** — patterns that are unambiguous on their own.
  A match here triggers an immediate emergency verdict; the LLM
  Stage 2 confirmation is skipped.
* **Stage 1.5 (ambiguous)** — patterns that frequently occur in
  non-emergency contexts (e.g. ``"chest pain"`` in a question about
  causes of chest pain). When one of these matches AND no clear
  pattern matches, Stage 2 LLM confirmation is invoked if enabled.

The split is interpretive — Part 5 §5.1 calls for "a short list of
ambiguous-case triggers" without enumerating them. The list here was
derived by picking phrases from the §5.2 list that read as
information-seeking when prefixed with phrases like "what is" or
"I read about". The exact split is documented in the conflicts log
and is intended to be tuned with real fixture data.

Each compiled pattern carries:

* ``name`` — short stable identifier returned in
  ``SafetyCheckResponse.detected_pattern``
* ``regex`` — case-insensitive, Unicode-aware compiled regex
* ``category`` — ``EmergencyCategory`` value
* ``tier`` — ``"clear"`` or ``"ambiguous"``
* ``language`` — ``"en"`` or ``"ar"``
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from services.safety_service.models.schemas import EmergencyCategory
from services.safety_service.services.arabic_normalizer import (
    normalise_for_matching,
)

PatternTier = Literal["clear", "ambiguous"]
PatternLanguage = Literal["en", "ar"]


@dataclass(frozen=True)
class EmergencyPattern:
    """One compiled emergency pattern."""

    name: str
    regex: re.Pattern[str]
    category: EmergencyCategory
    tier: PatternTier
    language: PatternLanguage


def _compile(*alternatives: str) -> re.Pattern[str]:
    """Compile a case-insensitive Unicode regex from word alternatives.

    Each alternative is passed through ``normalise_for_matching`` before
    being joined so the pattern matches the same normalised form the
    detector produces from user input. This is essential for Arabic —
    the input ``أزمة قلبية`` becomes ``ازمه قلبيه`` after hamza/ta-marbuta
    normalisation, and the compiled pattern must reflect that.
    """
    normalised_alternatives = [normalise_for_matching(alt) for alt in alternatives]
    joined = "|".join(normalised_alternatives)
    # Word boundaries are deliberately omitted — Arabic patterns can't
    # rely on \b semantics and English phrases like "can't breathe"
    # contain apostrophes that interact badly with word boundaries.
    return re.compile(f"({joined})", re.IGNORECASE | re.UNICODE)


# ─── English patterns ────────────────────────────────────────────


_EN_CLEAR: list[EmergencyPattern] = [
    EmergencyPattern(
        name="chest_pain",
        regex=_compile(
            r"i have chest pain",
            r"my chest hurts",
            r"crushing chest",
            r"chest tightness",
            r"chest pressure",
            r"pain in my chest",
            r"heart pain",
        ),
        category="cardiac",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="cannot_breathe",
        regex=_compile(
            r"can't breathe",
            r"cannot breathe",
            r"can not breathe",
            r"i'm not breathing",
            r"struggling to breathe",
        ),
        category="respiratory",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="stroke",
        regex=_compile(
            r"having a stroke",
            r"facial drooping",
            r"face is drooping",
            r"sudden numbness",
            r"sudden weakness on one side",
        ),
        category="stroke",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="unconscious",
        regex=_compile(
            r"unconscious",
            r"unresponsive",
            r"passed out",
            r"not responding",
            r"collapsed",
        ),
        category="loss_of_consciousness",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="seizure",
        regex=_compile(
            r"having a seizure",
            r"convulsion",
            r"epileptic attack",
            r"fitting now",
        ),
        category="seizure",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="severe_bleeding",
        regex=_compile(
            r"severe bleeding",
            r"uncontrolled bleeding",
            r"bleeding won't stop",
            r"bleeding wont stop",
            r"blood everywhere",
        ),
        category="bleeding",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="anaphylaxis",
        regex=_compile(
            r"anaphylaxis",
            r"severe allergic reaction",
            r"throat closing",
            r"tongue swelling",
            r"can't swallow",
            r"cannot swallow",
        ),
        category="allergic",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="overdose",
        regex=_compile(
            r"overdose",
            r"took too many",
            r"accidental ingestion",
            r"swallowed too much",
            r"poisoning",
        ),
        category="overdose",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="suicidal_ideation",
        regex=_compile(
            r"suicidal",
            r"want to die",
            r"going to kill myself",
            r"end my life",
            r"end it all",
            # NOTE: bare "suicide" omitted on purpose — "suicide
            # prevention" or "researching suicide rates" would
            # otherwise trip a false positive. ``suicidal`` covers
            # the first-person framing.
        ),
        category="mental_health_crisis",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="heart_attack",
        regex=_compile(
            r"having a heart attack",
            r"cardiac arrest",
            r"myocardial infarction",
        ),
        category="cardiac",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="severe_abdominal_pain",
        regex=_compile(
            r"severe abdominal pain",
            r"my abdomen is rigid",
            r"abdomen is rigid",
        ),
        category="abdominal",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="head_injury",
        regex=_compile(
            r"severe head injury",
            r"skull fracture",
            r"severe head trauma",
        ),
        category="head_injury",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="pediatric_ingestion",
        regex=_compile(
            r"child swallowed",
            r"baby swallowed",
            r"infant ingested",
            r"my kid ate.*(medication|pills|tablets)",
        ),
        category="ingestion",
        tier="clear",
        language="en",
    ),
    EmergencyPattern(
        name="explicit_emergency_request",
        regex=_compile(
            r"call (911|999|112|ambulance)",
            r"need an ambulance",
            r"go to the er now",
            r"ER right now",
        ),
        category="unspecified",
        tier="clear",
        language="en",
    ),
]


_EN_AMBIGUOUS: list[EmergencyPattern] = [
    EmergencyPattern(
        name="chest_pain_unspecified",
        regex=_compile(r"chest pain", r"chest pressure"),
        category="cardiac",
        tier="ambiguous",
        language="en",
    ),
    EmergencyPattern(
        name="breathing_difficulty_unspecified",
        regex=_compile(r"shortness of breath", r"difficulty breathing"),
        category="respiratory",
        tier="ambiguous",
        language="en",
    ),
    EmergencyPattern(
        name="stroke_unspecified",
        regex=_compile(r"stroke symptoms", r"signs of stroke", r"arm weakness"),
        category="stroke",
        tier="ambiguous",
        language="en",
    ),
    EmergencyPattern(
        name="suicide_unspecified",
        regex=_compile(r"suicide"),
        category="mental_health_crisis",
        tier="ambiguous",
        language="en",
    ),
    EmergencyPattern(
        name="bleeding_unspecified",
        regex=_compile(r"\bbleeding\b"),
        category="bleeding",
        tier="ambiguous",
        language="en",
    ),
]


# ─── Arabic patterns (Part 5 §5.2 verbatim) ──────────────────────


_AR_CLEAR: list[EmergencyPattern] = [
    EmergencyPattern(
        name="chest_pain_ar",
        regex=_compile(
            "ألم في الصدر",
            "ضيق في الصدر",
            "وجع في القلب",
            "ألم قلبي",
        ),
        category="cardiac",
        tier="clear",
        language="ar",
    ),
    EmergencyPattern(
        name="cannot_breathe_ar",
        regex=_compile(
            "صعوبة في التنفس",
            "ما أقدر أتنفس",
            "ما أقدر أنفس",
            "لهاث شديد",
        ),
        category="respiratory",
        tier="clear",
        language="ar",
    ),
    EmergencyPattern(
        name="stroke_ar",
        regex=_compile(
            "سكتة دماغية",
            "تدلي وجه",
            "ضعف مفاجئ",
        ),
        category="stroke",
        tier="clear",
        language="ar",
    ),
    EmergencyPattern(
        name="unconscious_ar",
        regex=_compile(
            "فقدان الوعي",
            "إغماء",
            "فقدان الاستجابة",
            "ما يرد علي",
        ),
        category="loss_of_consciousness",
        tier="clear",
        language="ar",
    ),
    EmergencyPattern(
        name="seizure_ar",
        regex=_compile(
            "نوبة صرع",
            "تشنجات",
        ),
        category="seizure",
        tier="clear",
        language="ar",
    ),
    EmergencyPattern(
        name="severe_bleeding_ar",
        regex=_compile(
            "نزيف حاد",
            "نزيف ما يوقف",
            "نزيف شديد",
        ),
        category="bleeding",
        tier="clear",
        language="ar",
    ),
    EmergencyPattern(
        name="anaphylaxis_ar",
        regex=_compile(
            "حساسية شديدة",
            "حساسية مفاجئة",
            "تورم الحلق",
            "ما أقدر أبلع",
        ),
        category="allergic",
        tier="clear",
        language="ar",
    ),
    EmergencyPattern(
        name="overdose_ar",
        regex=_compile(
            "جرعة زائدة",
            "ابتلع كثير من الدواء",
            "تسمم",
            "ابتلع أدوية",
        ),
        category="overdose",
        tier="clear",
        language="ar",
    ),
    EmergencyPattern(
        name="suicidal_ar",
        regex=_compile(
            "أفكار انتحارية",
            "بدي أموت",
            "أنهي حياتي",
        ),
        category="mental_health_crisis",
        tier="clear",
        language="ar",
    ),
    EmergencyPattern(
        name="heart_attack_ar",
        regex=_compile(
            "أزمة قلبية",
            "سكتة قلبية",
            "توقف القلب",
        ),
        category="cardiac",
        tier="clear",
        language="ar",
    ),
    EmergencyPattern(
        name="severe_abdominal_pain_ar",
        regex=_compile(
            "ألم في البطن الشديد",
            "بطن منتفخ وصلب",
        ),
        category="abdominal",
        tier="clear",
        language="ar",
    ),
    EmergencyPattern(
        name="pediatric_ingestion_ar",
        regex=_compile(
            "الطفل ابتلع",
            "الرضيع ابتلع",
            "الصغير أكل دواء",
        ),
        category="ingestion",
        tier="clear",
        language="ar",
    ),
    EmergencyPattern(
        name="explicit_emergency_ar",
        regex=_compile(
            "إسعاف",
            "طوارئ الآن",
            "اتصل بالإسعاف",
        ),
        category="unspecified",
        tier="clear",
        language="ar",
    ),
]


_AR_AMBIGUOUS: list[EmergencyPattern] = [
    EmergencyPattern(
        name="suicide_unspecified_ar",
        regex=_compile("انتحار"),
        category="mental_health_crisis",
        tier="ambiguous",
        language="ar",
    ),
    EmergencyPattern(
        name="bleeding_unspecified_ar",
        regex=_compile("نزيف"),
        category="bleeding",
        tier="ambiguous",
        language="ar",
    ),
]


# ─── public collections ──────────────────────────────────────────


ALL_CLEAR_PATTERNS: tuple[EmergencyPattern, ...] = tuple(_EN_CLEAR + _AR_CLEAR)
ALL_AMBIGUOUS_PATTERNS: tuple[EmergencyPattern, ...] = tuple(_EN_AMBIGUOUS + _AR_AMBIGUOUS)


__all__ = [
    "ALL_AMBIGUOUS_PATTERNS",
    "ALL_CLEAR_PATTERNS",
    "EmergencyPattern",
    "PatternLanguage",
    "PatternTier",
]
