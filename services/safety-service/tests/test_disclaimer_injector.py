"""Tests for DisclaimerInjector and pregnancy rules."""

from __future__ import annotations

import pytest

from services.safety_service.exceptions.exceptions import InvalidSafetyInput
from services.safety_service.models.schemas import (
    SafetyWrapRequest,
    UserProfile,
)
from services.safety_service.services.disclaimer_injector import (
    DISCLAIMER_AR,
    DISCLAIMER_EN,
    DisclaimerInjector,
    get_disclaimer,
)
from services.safety_service.services.pregnancy_rules import (
    get_pregnancy_warning_for,
)

# ─── Disclaimer presence ──────────────────────────────────────────


def test_disclaimer_always_attached() -> None:
    injector = DisclaimerInjector()
    request = SafetyWrapRequest(
        response_content="Some content",
        language="en",
    )
    response = injector.wrap(request)
    assert response.disclaimer_en == DISCLAIMER_EN
    assert response.disclaimer_ar == DISCLAIMER_AR


def test_wrapped_content_unchanged() -> None:
    injector = DisclaimerInjector()
    request = SafetyWrapRequest(
        response_content="Original medical text here.",
        language="en",
    )
    response = injector.wrap(request)
    assert response.wrapped_content == "Original medical text here."


def test_get_disclaimer_picks_language() -> None:
    assert get_disclaimer("en") == DISCLAIMER_EN
    assert get_disclaimer("ar") == DISCLAIMER_AR


# ─── Pregnancy rules — lookup ─────────────────────────────────────


@pytest.mark.parametrize(
    "drug, expected_severity",
    [
        ("ibuprofen", "high"),
        ("warfarin", "critical"),
        ("isotretinoin", "critical"),
        ("atorvastatin", "high"),
        ("lisinopril", "critical"),
        ("methotrexate", "critical"),
        ("doxycycline", "high"),
    ],
)
def test_pregnancy_warning_lookup_matches(drug: str, expected_severity: str) -> None:
    warning = get_pregnancy_warning_for(drug)
    assert warning is not None
    assert warning.severity == expected_severity
    assert warning.drug == drug
    assert warning.type == "pregnancy_warning"
    assert "PREGNANCY" in warning.message_en or "pregnancy" in warning.message_en.lower()
    assert "تنبيه للحمل" in warning.message_ar


def test_pregnancy_warning_case_insensitive() -> None:
    warning = get_pregnancy_warning_for("WARFARIN")
    assert warning is not None
    assert warning.drug == "warfarin"


def test_unknown_drug_returns_none() -> None:
    assert get_pregnancy_warning_for("paracetamol") is None
    assert get_pregnancy_warning_for("amoxicillin") is None
    assert get_pregnancy_warning_for("") is None


# ─── /safety/wrap — pregnancy warning attachment ──────────────────


def test_pregnant_user_drug_context_attaches_warning() -> None:
    injector = DisclaimerInjector()
    request = SafetyWrapRequest(
        response_content="Ibuprofen reduces inflammation by inhibiting COX enzymes.",
        language="en",
        user_profile=UserProfile(is_pregnant=True),
        context="drug_profile",
        drug_names=["ibuprofen"],
    )
    response = injector.wrap(request)
    assert len(response.profile_warnings) == 1
    assert response.profile_warnings[0].drug == "ibuprofen"
    assert response.profile_warnings[0].type == "pregnancy_warning"


def test_pregnant_user_non_drug_context_does_not_warn() -> None:
    """A chatbot answer mentioning ibuprofen in passing shouldn't trigger."""
    injector = DisclaimerInjector()
    request = SafetyWrapRequest(
        response_content="Some people use ibuprofen for headaches.",
        language="en",
        user_profile=UserProfile(is_pregnant=True),
        context="chatbot_response",  # not drug_*
        drug_names=["ibuprofen"],
    )
    response = injector.wrap(request)
    assert response.profile_warnings == []


def test_non_pregnant_user_no_warning() -> None:
    injector = DisclaimerInjector()
    request = SafetyWrapRequest(
        response_content="Ibuprofen dosing info.",
        language="en",
        user_profile=UserProfile(is_pregnant=False),
        context="drug_profile",
        drug_names=["ibuprofen"],
    )
    response = injector.wrap(request)
    assert response.profile_warnings == []


def test_unknown_drug_for_pregnant_user_no_warning() -> None:
    """No data on a drug = no false-positive warning."""
    injector = DisclaimerInjector()
    request = SafetyWrapRequest(
        response_content="Paracetamol info.",
        language="en",
        user_profile=UserProfile(is_pregnant=True),
        context="drug_profile",
        drug_names=["paracetamol"],
    )
    response = injector.wrap(request)
    assert response.profile_warnings == []


def test_multiple_drugs_attaches_multiple_warnings() -> None:
    injector = DisclaimerInjector()
    request = SafetyWrapRequest(
        response_content="Drug interaction analysis...",
        language="en",
        user_profile=UserProfile(is_pregnant=True),
        context="drug_interaction",
        drug_names=["ibuprofen", "warfarin", "paracetamol"],
    )
    response = injector.wrap(request)
    # Two known + one unknown → two warnings
    assert len(response.profile_warnings) == 2
    drugs_warned = {w.drug for w in response.profile_warnings}
    assert drugs_warned == {"ibuprofen", "warfarin"}


def test_duplicate_drugs_deduped() -> None:
    injector = DisclaimerInjector()
    request = SafetyWrapRequest(
        response_content="...",
        language="en",
        user_profile=UserProfile(is_pregnant=True),
        context="drug_dosage",
        drug_names=["ibuprofen", "Ibuprofen", "IBUPROFEN"],
    )
    response = injector.wrap(request)
    assert len(response.profile_warnings) == 1


# ─── Semantic validation ──────────────────────────────────────────


def test_pregnancy_trimester_without_is_pregnant_raises() -> None:
    injector = DisclaimerInjector()
    request = SafetyWrapRequest(
        response_content="content",
        language="en",
        user_profile=UserProfile(is_pregnant=False, pregnancy_trimester=2),
        context="generic",
    )
    with pytest.raises(InvalidSafetyInput):
        injector.wrap(request)
