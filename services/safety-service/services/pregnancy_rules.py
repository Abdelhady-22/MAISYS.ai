"""Drug-against-profile rule lookups for ``/safety/wrap``.

When the calling service sends a response that mentions a drug AND
the user's profile says ``is_pregnant=true`` or contains relevant
chronic conditions, we attach a ``ProfileWarning`` to the response
so the UI can surface it as a banner.

The rules are intentionally a small, curated hardcoded table — not a
catalog of every contraindication. The goal is to catch the
highest-risk combinations reliably. Calling services that need
exhaustive interaction data go to drug-service for that — safety
just surfaces the cases that should be hard to miss.

Sources for the pregnancy-category assignments are FDA-approved
labelling. Some drugs (warfarin, isotretinoin, statins,
methotrexate) carry FDA Category X — outright contraindicated. Others
(ibuprofen, ACE inhibitors, ARBs) are Category D — risk demonstrated
but use sometimes justified. The phrasing reflects that distinction.

This list is documented in P3-C05 as a conflicts-log entry: the long
form (full FDA pregnancy categorisation for every drug) is out of
scope for Phase 3 and tracked for a later expansion (a YAML config
file loaded at startup so the team can iterate without code changes).
"""

from __future__ import annotations

from dataclasses import dataclass

from services.safety_service.models.schemas import ProfileWarning, Severity


@dataclass(frozen=True)
class PregnancyRule:
    drug: str
    """Normalised generic name (lowercased, no brand)."""

    severity: Severity
    message_en: str
    message_ar: str


# Curated starter set. Pregnancy-category-X drugs (highest severity).
_RULES_X: list[PregnancyRule] = [
    PregnancyRule(
        drug="warfarin",
        severity="critical",
        message_en=(
            "⚠️ PREGNANCY ALERT: Warfarin is contraindicated in pregnancy. "
            "It can cross the placenta and cause fetal warfarin syndrome "
            "and bleeding. Do not start or continue without an obstetrician "
            "and haematologist consulting on alternatives."
        ),
        message_ar=(
            "⚠️ تنبيه للحمل: الوارفارين ممنوع خلال الحمل. يمكن أن يعبر المشيمة "
            "ويسبب متلازمة الوارفارين الجنينية ونزيفاً. لا تبدأ أو تستمر دون "
            "استشارة طبيب نساء وتوليد وأخصائي أمراض دم بشأن البدائل."
        ),
    ),
    PregnancyRule(
        drug="isotretinoin",
        severity="critical",
        message_en=(
            "⚠️ PREGNANCY ALERT: Isotretinoin causes severe birth defects "
            "and is absolutely contraindicated in pregnancy. Stop the "
            "medication and contact your prescriber immediately."
        ),
        message_ar=(
            "⚠️ تنبيه للحمل: الإيزوتريتينوين يسبب عيوباً خلقية شديدة وممنوع "
            "تماماً خلال الحمل. توقف عن الدواء واتصل بالطبيب الواصف فوراً."
        ),
    ),
    PregnancyRule(
        drug="atorvastatin",
        severity="high",
        message_en=(
            "⚠️ PREGNANCY ALERT: Statins including atorvastatin are not "
            "recommended in pregnancy. Discuss alternatives with your "
            "cardiologist before continuing."
        ),
        message_ar=(
            "⚠️ تنبيه للحمل: أدوية الستاتين بما فيها أتورفاستاتين غير موصى بها "
            "خلال الحمل. ناقش البدائل مع طبيب القلب قبل الاستمرار."
        ),
    ),
    PregnancyRule(
        drug="simvastatin",
        severity="high",
        message_en=(
            "⚠️ PREGNANCY ALERT: Statins including simvastatin are not "
            "recommended in pregnancy. Discuss alternatives with your "
            "cardiologist before continuing."
        ),
        message_ar=(
            "⚠️ تنبيه للحمل: أدوية الستاتين بما فيها سيمفاستاتين غير موصى بها "
            "خلال الحمل. ناقش البدائل مع طبيب القلب قبل الاستمرار."
        ),
    ),
    PregnancyRule(
        drug="methotrexate",
        severity="critical",
        message_en=(
            "⚠️ PREGNANCY ALERT: Methotrexate is contraindicated in "
            "pregnancy — it can cause severe birth defects and pregnancy "
            "loss. Do not take. Contact your prescriber today."
        ),
        message_ar=(
            "⚠️ تنبيه للحمل: الميثوتريكسات ممنوع خلال الحمل — يمكن أن يسبب "
            "عيوباً خلقية شديدة وفقدان الحمل. لا تتناوله. اتصل بالطبيب اليوم."
        ),
    ),
]


# Category-D — risk demonstrated but use may be justified.
_RULES_D: list[PregnancyRule] = [
    PregnancyRule(
        drug="ibuprofen",
        severity="high",
        message_en=(
            "⚠️ PREGNANCY ALERT: Ibuprofen should be avoided during pregnancy, "
            "especially in the third trimester, due to risk of harm to the "
            "developing baby. Consult your obstetrician before use."
        ),
        message_ar=(
            "⚠️ تنبيه للحمل: يجب تجنب الإيبوبروفين خلال الحمل، خاصة في الثلث "
            "الثالث، بسبب خطر الإضرار بالجنين. استشيري طبيب النساء قبل الاستخدام."
        ),
    ),
    PregnancyRule(
        drug="aspirin",
        severity="high",
        message_en=(
            "⚠️ PREGNANCY ALERT: Full-dose aspirin should be avoided in "
            "pregnancy, especially the third trimester. Low-dose aspirin "
            "is sometimes prescribed in specific cases — do not start or "
            "stop without obstetric advice."
        ),
        message_ar=(
            "⚠️ تنبيه للحمل: يجب تجنب الجرعة الكاملة من الأسبرين في الحمل، "
            "خاصة في الثلث الثالث. تُوصف جرعات منخفضة في حالات محددة — "
            "لا تبدأي أو تتوقفي دون استشارة طبيب النساء."
        ),
    ),
    PregnancyRule(
        drug="lisinopril",
        severity="critical",
        message_en=(
            "⚠️ PREGNANCY ALERT: ACE inhibitors including lisinopril can "
            "cause serious harm to the developing baby in the second and "
            "third trimesters and should not be used in pregnancy. "
            "Contact your prescriber immediately."
        ),
        message_ar=(
            "⚠️ تنبيه للحمل: مثبطات الإنزيم المحول للأنجيوتنسين بما فيها "
            "ليزينوبريل قد تسبب ضرراً جسيماً للجنين في الثلثين الثاني والثالث "
            "ولا يجب استخدامها في الحمل. اتصلي بالطبيب الواصف فوراً."
        ),
    ),
    PregnancyRule(
        drug="enalapril",
        severity="critical",
        message_en=(
            "⚠️ PREGNANCY ALERT: ACE inhibitors including enalapril can "
            "cause serious harm to the developing baby and should not be "
            "used in pregnancy. Contact your prescriber immediately."
        ),
        message_ar=(
            "⚠️ تنبيه للحمل: مثبطات الإنزيم المحول للأنجيوتنسين بما فيها "
            "إينالابريل قد تسبب ضرراً جسيماً للجنين ولا يجب استخدامها في الحمل. "
            "اتصلي بالطبيب الواصف فوراً."
        ),
    ),
    PregnancyRule(
        drug="losartan",
        severity="critical",
        message_en=(
            "⚠️ PREGNANCY ALERT: Angiotensin receptor blockers (ARBs) "
            "including losartan can harm the developing baby and should "
            "not be used in pregnancy. Contact your prescriber immediately."
        ),
        message_ar=(
            "⚠️ تنبيه للحمل: حاصرات مستقبلات الأنجيوتنسين بما فيها لوسارتان "
            "قد تضر الجنين ولا يجب استخدامها في الحمل. اتصلي بالطبيب الواصف فوراً."
        ),
    ),
    PregnancyRule(
        drug="doxycycline",
        severity="high",
        message_en=(
            "⚠️ PREGNANCY ALERT: Tetracyclines including doxycycline are "
            "not recommended in pregnancy after the first trimester due to "
            "risk of tooth and bone development effects. Discuss "
            "alternatives with your obstetrician."
        ),
        message_ar=(
            "⚠️ تنبيه للحمل: التتراسيكلينات بما فيها دوكسيسايكلين غير موصى بها "
            "في الحمل بعد الثلث الأول بسبب خطر التأثير على نمو الأسنان والعظام. "
            "ناقشي البدائل مع طبيب النساء."
        ),
    ),
]


_BY_DRUG: dict[str, PregnancyRule] = {rule.drug: rule for rule in (*_RULES_X, *_RULES_D)}


def get_pregnancy_warning_for(drug_name: str) -> ProfileWarning | None:
    """Return a ``ProfileWarning`` for ``drug_name`` if a rule applies.

    The match is on lowercased exact equality of the generic name —
    callers normalise via drug-service's RxNorm flow before calling
    safety-service. No fuzzy matching here; that's a different
    service's job and would muddy the safety boundary.
    """
    if not drug_name:
        return None
    rule = _BY_DRUG.get(drug_name.strip().lower())
    if rule is None:
        return None
    return ProfileWarning(
        type="pregnancy_warning",
        severity=rule.severity,
        message_en=rule.message_en,
        message_ar=rule.message_ar,
        drug=rule.drug,
    )


__all__ = ["PregnancyRule", "get_pregnancy_warning_for"]
