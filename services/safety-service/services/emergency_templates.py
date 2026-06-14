"""Emergency response template builder.

Given a detected emergency category, build the bilingual response
payload that Part 5 §5.3 specifies. Templates are kept in this
module rather than a config file because they're a small, fixed set
that benefits from type-checking, and there's no operational reason
to change them at runtime.

Country-specific emergency numbers (911 / 999 / 112 / Saudi 920000)
are listed in every English/Arabic action set per the §5.3 example —
the user's actual country is not known here (safety-service is
stateless), so we include all common numbers and let the UI render
the relevant one if it has the country code from elsewhere.
"""

from __future__ import annotations

from services.safety_service.models.schemas import (
    EmergencyCategory,
    EmergencyResponse,
)

# Generic emergency payload from Part 5 §5.3 — used as the fallback
# for categories without a specific template and as the base for
# category-specific overrides.
_GENERIC_EN_TITLE = "\u26a0\ufe0f This may be a medical emergency"
_GENERIC_AR_TITLE = "\u26a0\ufe0f قد تكون هذه حالة طوارئ طبية"

_GENERIC_EN_MESSAGE = (
    "Your message contains symptoms that may indicate a serious medical "
    "emergency. Please stop using this app and seek immediate medical help."
)
_GENERIC_AR_MESSAGE = (
    "رسالتك تحتوي على أعراض قد تشير إلى حالة طوارئ طبية خطيرة. "
    "يرجى التوقف عن استخدام هذا التطبيق وطلب المساعدة الطبية الفورية."
)

_GENERIC_EN_ACTIONS = [
    "Call emergency services immediately (911 in US, 999 in UK, 112 in EU, 911/920000 in Saudi Arabia)",
    "Go to the nearest emergency room",
    "If safe to do so — do not drive yourself, call an ambulance",
]
_GENERIC_AR_ACTIONS = [
    "اتصل بالإسعاف فوراً (911 أو 911 السعودية 920000)",
    "اذهب إلى أقرب غرفة طوارئ",
    "إذا كان ذلك آمناً، لا تقود السيارة بنفسك — اطلب سيارة إسعاف",
]


# Category-specific overrides for the message text. The actions
# stay identical across categories — the only category-tuned
# difference is the explanatory message.
_CATEGORY_MESSAGES: dict[EmergencyCategory, tuple[str, str]] = {
    "mental_health_crisis": (
        # English message
        "It sounds like you may be having thoughts of suicide or self-harm. "
        "You are not alone — please reach out to a crisis line right now. "
        "If you are in immediate danger, please call emergency services.",
        # Arabic message
        "يبدو أنك قد تمر بأفكار انتحارية أو رغبة في إيذاء النفس. "
        "لست وحدك — يرجى التواصل مع خط أزمات فوراً. "
        "إذا كنت في خطر مباشر، يرجى الاتصال بخدمات الطوارئ.",
    ),
    "overdose": (
        "Your message mentions an overdose or accidental ingestion. "
        "Stop and contact poison control or emergency services immediately — "
        "even if you feel fine right now, some overdoses are time-sensitive.",
        "رسالتك تذكر جرعة زائدة أو ابتلاعاً عرضياً. توقف واتصل بمركز السموم أو "
        "خدمات الطوارئ فوراً — حتى إذا كنت تشعر بأنك بخير الآن، بعض الجرعات الزائدة حساسة للوقت.",
    ),
    "cardiac": (
        "Your message describes possible heart-related emergency symptoms. "
        "Stop activity, sit or lie down, and call emergency services now.",
        "رسالتك تصف أعراض طوارئ قلبية محتملة. توقف عن النشاط، اجلس أو استلقِ، "
        "واتصل بخدمات الطوارئ الآن.",
    ),
    "stroke": (
        "Your message describes possible stroke symptoms. Time is critical — "
        "every minute matters. Call emergency services immediately and note "
        "exactly when symptoms started.",
        "رسالتك تصف أعراض سكتة دماغية محتملة. الوقت حرج — كل دقيقة مهمة. "
        "اتصل بخدمات الطوارئ فوراً ولاحظ متى بدأت الأعراض بالضبط.",
    ),
    "respiratory": (
        "Your message describes a severe breathing problem. "
        "Stay upright, try to stay calm, and call emergency services now.",
        "رسالتك تصف مشكلة تنفسية شديدة. ابقَ في وضع مستقيم، حاول أن تبقى هادئاً، "
        "واتصل بخدمات الطوارئ الآن.",
    ),
    "bleeding": (
        "Your message describes severe or uncontrolled bleeding. "
        "Apply firm pressure to the wound with a clean cloth and call "
        "emergency services immediately.",
        "رسالتك تصف نزيفاً حاداً أو غير مسيطر عليه. اضغط بقوة على الجرح بقطعة قماش "
        "نظيفة واتصل بخدمات الطوارئ فوراً.",
    ),
    "allergic": (
        "Your message describes a severe allergic reaction. "
        "If you have an epinephrine auto-injector, use it now. "
        "Call emergency services immediately.",
        "رسالتك تصف حساسية شديدة. إذا كان لديك حاقن إيبينفرين تلقائي، استخدمه الآن. "
        "اتصل بخدمات الطوارئ فوراً.",
    ),
    "seizure": (
        "Your message describes a seizure happening now or just ending. "
        "If someone is seizing, protect their head, do not put anything in "
        "their mouth, and call emergency services.",
        "رسالتك تصف نوبة تشنج تحدث الآن أو انتهت للتو. إذا كان شخص يتشنج، "
        "احمِ رأسه، لا تضع أي شيء في فمه، واتصل بخدمات الطوارئ.",
    ),
    "ingestion": (
        "A child has swallowed something potentially dangerous. "
        "Do not induce vomiting — call poison control or emergency services "
        "immediately and bring the container if you can.",
        "ابتلع طفل شيئاً قد يكون خطيراً. لا تحفز التقيؤ — اتصل بمركز السموم أو "
        "خدمات الطوارئ فوراً وأحضر العبوة إن أمكن.",
    ),
}


def build_emergency_response(category: EmergencyCategory) -> EmergencyResponse:
    """Build the bilingual ``EmergencyResponse`` for a given category.

    Categories without a tailored message fall back to the generic
    Part 5 §5.3 template. ``actions`` and ``do_not_wait`` /
    ``session_should_halt`` are constant — the calling UI is always
    expected to halt the user's current flow on an emergency.
    """
    en_msg, ar_msg = _CATEGORY_MESSAGES.get(category, (_GENERIC_EN_MESSAGE, _GENERIC_AR_MESSAGE))
    return EmergencyResponse(
        title_en=_GENERIC_EN_TITLE,
        title_ar=_GENERIC_AR_TITLE,
        message_en=en_msg,
        message_ar=ar_msg,
        actions_en=list(_GENERIC_EN_ACTIONS),
        actions_ar=list(_GENERIC_AR_ACTIONS),
        do_not_wait=True,
        session_should_halt=True,
    )


__all__ = ["build_emergency_response"]
