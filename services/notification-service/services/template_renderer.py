"""Template definitions and rendering.

Part 5 §7.2 enumerates 5 bilingual email templates. Templates live
here as Python constants rather than separate files because:

* the set is small and fixed
* type-checking catches mistakes earlier than file loading
* the rendering tests can import them directly without a temp dir

If the set grows beyond ~10, migrating to a ``templates/`` folder
with one file per (template, language, part) and a glob-based loader
is straightforward — the ``render`` function below is the only
caller, so swapping the storage is a single-file change.

Each template defines:

* ``subject`` — bilingual {en, ar}
* ``html_body`` — bilingual {en, ar} HTML (kept simple — no inlined CSS)
* ``text_body`` — bilingual {en, ar} plain-text fallback
* ``required_vars`` — set of variable names the template uses

``required_vars`` is verified at render time — a missing variable
fails fast with ``TemplateVariableMissing`` rather than rendering an
empty string into a customer's OTP email.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jinja2 import Environment, StrictUndefined, select_autoescape

from services.notification_service.exceptions.exceptions import (
    TemplateNotFound,
    TemplateVariableMissing,
)
from services.notification_service.models.schemas import Language, NotificationType


@dataclass(frozen=True)
class TemplateDefinition:
    subject: dict[Language, str]
    html_body: dict[Language, str]
    text_body: dict[Language, str]
    required_vars: frozenset[str]


# ─── Templates ────────────────────────────────────────────────────


_T_EMAIL_VERIFY = TemplateDefinition(
    subject={
        "en": "Verify your MAISYS email address",
        "ar": "تحقق من عنوان بريدك الإلكتروني في MAISYS",
    },
    html_body={
        "en": (
            "<p>Hi {{ user_name }},</p>"
            "<p>Your MAISYS verification code is:</p>"
            '<h2 style="letter-spacing:4px">{{ otp_code }}</h2>'
            "<p>This code expires in {{ expires_in_minutes }} minutes.</p>"
            "<p>If you didn't request this, ignore this email — no further action is required.</p>"
        ),
        "ar": (
            '<p dir="rtl">مرحباً {{ user_name }}،</p>'
            '<p dir="rtl">رمز التحقق من حسابك في MAISYS هو:</p>'
            '<h2 dir="rtl" style="letter-spacing:4px">{{ otp_code }}</h2>'
            '<p dir="rtl">ينتهي صلاحية هذا الرمز خلال {{ expires_in_minutes }} دقيقة.</p>'
            '<p dir="rtl">إذا لم تطلب هذا، تجاهل هذا البريد — لا يلزم اتخاذ أي إجراء.</p>'
        ),
    },
    text_body={
        "en": (
            "Hi {{ user_name }},\n\n"
            "Your MAISYS verification code is: {{ otp_code }}\n"
            "This code expires in {{ expires_in_minutes }} minutes.\n\n"
            "If you didn't request this, ignore this email."
        ),
        "ar": (
            "مرحباً {{ user_name }}،\n\n"
            "رمز التحقق من حسابك في MAISYS: {{ otp_code }}\n"
            "ينتهي صلاحية هذا الرمز خلال {{ expires_in_minutes }} دقيقة.\n\n"
            "إذا لم تطلب هذا، تجاهل هذا البريد."
        ),
    },
    required_vars=frozenset({"user_name", "otp_code", "expires_in_minutes"}),
)


_T_PASSWORD_RESET = TemplateDefinition(
    subject={
        "en": "Reset your MAISYS password",
        "ar": "إعادة تعيين كلمة مرور MAISYS",
    },
    html_body={
        "en": (
            "<p>Hi {{ user_name }},</p>"
            "<p>We received a request to reset your MAISYS password.</p>"
            "<p>Your reset code is:</p>"
            '<h2 style="letter-spacing:4px">{{ otp_code }}</h2>'
            "<p>This code expires in {{ expires_in_minutes }} minutes.</p>"
            "<p>If you didn't request a password reset, ignore this email and your password will stay unchanged.</p>"
        ),
        "ar": (
            '<p dir="rtl">مرحباً {{ user_name }}،</p>'
            '<p dir="rtl">تلقينا طلباً لإعادة تعيين كلمة مرورك في MAISYS.</p>'
            '<p dir="rtl">رمز إعادة التعيين الخاص بك هو:</p>'
            '<h2 dir="rtl" style="letter-spacing:4px">{{ otp_code }}</h2>'
            '<p dir="rtl">ينتهي صلاحية هذا الرمز خلال {{ expires_in_minutes }} دقيقة.</p>'
            '<p dir="rtl">إذا لم تطلب إعادة تعيين كلمة المرور، تجاهل هذا البريد.</p>'
        ),
    },
    text_body={
        "en": (
            "Hi {{ user_name }},\n\n"
            "Your MAISYS password reset code: {{ otp_code }}\n"
            "Expires in {{ expires_in_minutes }} minutes.\n\n"
            "If you didn't request this, ignore this email."
        ),
        "ar": (
            "مرحباً {{ user_name }}،\n\n"
            "رمز إعادة تعيين كلمة مرورك في MAISYS: {{ otp_code }}\n"
            "ينتهي صلاحيته خلال {{ expires_in_minutes }} دقيقة.\n\n"
            "إذا لم تطلب هذا، تجاهل هذا البريد."
        ),
    },
    required_vars=frozenset({"user_name", "otp_code", "expires_in_minutes"}),
)


_T_LOGIN_OTP = TemplateDefinition(
    subject={
        "en": "Your MAISYS login code",
        "ar": "رمز تسجيل الدخول إلى MAISYS",
    },
    html_body={
        "en": (
            "<p>Your MAISYS login code is:</p>"
            '<h2 style="letter-spacing:4px">{{ otp_code }}</h2>'
            "<p>Valid for {{ expires_in_minutes }} minutes. If you didn't request this code, please secure your account.</p>"
        ),
        "ar": (
            '<p dir="rtl">رمز تسجيل الدخول إلى MAISYS:</p>'
            '<h2 dir="rtl" style="letter-spacing:4px">{{ otp_code }}</h2>'
            '<p dir="rtl">صالح لمدة {{ expires_in_minutes }} دقيقة. إذا لم تطلب هذا الرمز، يرجى تأمين حسابك.</p>'
        ),
    },
    text_body={
        "en": ("MAISYS login code: {{ otp_code }}\n" "Valid for {{ expires_in_minutes }} minutes."),
        "ar": (
            "رمز تسجيل الدخول إلى MAISYS: {{ otp_code }}\n"
            "صالح لمدة {{ expires_in_minutes }} دقيقة."
        ),
    },
    required_vars=frozenset({"otp_code", "expires_in_minutes"}),
)


_T_EXPORT_READY = TemplateDefinition(
    subject={
        "en": "Your MAISYS export is ready",
        "ar": "تصديرك من MAISYS جاهز",
    },
    html_body={
        "en": (
            "<p>Hi {{ user_name }},</p>"
            "<p>Your MAISYS export is ready to download:</p>"
            '<p><a href="{{ download_url }}">Download now</a></p>'
            "<p>This link expires in 24 hours.</p>"
        ),
        "ar": (
            '<p dir="rtl">مرحباً {{ user_name }}،</p>'
            '<p dir="rtl">تصديرك من MAISYS جاهز للتحميل:</p>'
            '<p dir="rtl"><a href="{{ download_url }}">حمّل الآن</a></p>'
            '<p dir="rtl">ينتهي صلاحية هذا الرابط خلال 24 ساعة.</p>'
        ),
    },
    text_body={
        "en": (
            "Hi {{ user_name }},\n\n"
            "Your MAISYS export is ready: {{ download_url }}\n"
            "Link expires in 24 hours."
        ),
        "ar": (
            "مرحباً {{ user_name }}،\n\n"
            "تصديرك من MAISYS جاهز: {{ download_url }}\n"
            "ينتهي صلاحية الرابط خلال 24 ساعة."
        ),
    },
    required_vars=frozenset({"user_name", "download_url"}),
)


_T_BETA_REVIEWED = TemplateDefinition(
    subject={
        "en": "Your MAISYS Beta feedback has been reviewed",
        "ar": "تمت مراجعة ملاحظات MAISYS Beta الخاصة بك",
    },
    html_body={
        "en": (
            "<p>Hi {{ user_name }},</p>"
            "<p>Thank you for participating in MAISYS Beta.</p>"
            "<p>Your session has been reviewed by our medical staff. "
            "For privacy reasons we cannot share individual results, but your feedback helps "
            "us improve MAISYS for everyone.</p>"
        ),
        "ar": (
            '<p dir="rtl">مرحباً {{ user_name }}،</p>'
            '<p dir="rtl">شكراً لمشاركتك في MAISYS Beta.</p>'
            '<p dir="rtl">تمت مراجعة جلستك من قبل فريقنا الطبي. '
            "لأسباب الخصوصية لا يمكننا مشاركة النتائج الفردية، "
            "لكن ملاحظاتك تساعدنا في تحسين MAISYS للجميع.</p>"
        ),
    },
    text_body={
        "en": (
            "Hi {{ user_name }},\n\n"
            "Your MAISYS Beta session has been reviewed by our medical staff. "
            "Thank you for participating."
        ),
        "ar": (
            "مرحباً {{ user_name }}،\n\n"
            "تمت مراجعة جلسة MAISYS Beta الخاصة بك من قبل فريقنا الطبي. شكراً لمشاركتك."
        ),
    },
    required_vars=frozenset({"user_name"}),
)


TEMPLATES: dict[NotificationType, TemplateDefinition] = {
    "email_verify": _T_EMAIL_VERIFY,
    "password_reset": _T_PASSWORD_RESET,
    "login_otp": _T_LOGIN_OTP,
    "export_ready": _T_EXPORT_READY,
    "beta_session_reviewed": _T_BETA_REVIEWED,
}


# ─── Renderer ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class RenderedEmail:
    """The bundle handed to the email adapter."""

    subject: str
    html_body: str
    text_body: str


# StrictUndefined: missing variables raise rather than rendering "" —
# safer for OTPs and other security-sensitive content.
_JINJA = Environment(
    autoescape=select_autoescape(default_for_string=False, default=False),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_email(
    template_name: NotificationType,
    language: Language,
    template_vars: dict[str, Any],
) -> RenderedEmail:
    """Render the bilingual template into a single-language email.

    Raises ``TemplateNotFound`` for unknown templates and
    ``TemplateVariableMissing`` for any required variable not in
    ``template_vars``. The Jinja2 StrictUndefined backstop catches
    any drift between ``required_vars`` and the actual template
    bodies — both checks together mean a typo is caught at render
    time, not at delivery time.
    """
    template = TEMPLATES.get(template_name)
    if template is None:
        raise TemplateNotFound(f"Template not registered: {template_name!r}")

    missing = template.required_vars - template_vars.keys()
    if missing:
        raise TemplateVariableMissing(
            f"Missing template variables for {template_name!r}: {sorted(missing)}"
        )

    subject = _JINJA.from_string(template.subject[language]).render(**template_vars)
    html_body = _JINJA.from_string(template.html_body[language]).render(**template_vars)
    text_body = _JINJA.from_string(template.text_body[language]).render(**template_vars)
    return RenderedEmail(subject=subject, html_body=html_body, text_body=text_body)


__all__ = [
    "RenderedEmail",
    "TEMPLATES",
    "TemplateDefinition",
    "render_email",
]
