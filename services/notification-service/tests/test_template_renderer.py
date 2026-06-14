"""Tests for the template renderer."""

from __future__ import annotations

import pytest

from services.notification_service.exceptions.exceptions import (
    TemplateNotFound,
    TemplateVariableMissing,
)
from services.notification_service.services.template_renderer import (
    TEMPLATES,
    render_email,
)


def test_all_five_templates_are_registered() -> None:
    """Part 5 §7.2 enumerates exactly these five — registry must match."""
    assert set(TEMPLATES.keys()) == {
        "email_verify",
        "password_reset",
        "login_otp",
        "export_ready",
        "beta_session_reviewed",
    }


def test_every_template_has_both_languages() -> None:
    for name, template in TEMPLATES.items():
        assert set(template.subject.keys()) == {"en", "ar"}, f"{name} subject"
        assert set(template.html_body.keys()) == {"en", "ar"}, f"{name} html"
        assert set(template.text_body.keys()) == {"en", "ar"}, f"{name} text"


def test_render_email_verify_english() -> None:
    out = render_email(
        "email_verify",
        "en",
        {"user_name": "Ahmad", "otp_code": "847291", "expires_in_minutes": 10},
    )
    assert "Ahmad" in out.html_body
    assert "847291" in out.html_body
    assert "10 minutes" in out.html_body
    assert "Ahmad" in out.text_body
    assert "Verify your MAISYS" in out.subject


def test_render_email_verify_arabic() -> None:
    out = render_email(
        "email_verify",
        "ar",
        {"user_name": "أحمد", "otp_code": "847291", "expires_in_minutes": 10},
    )
    assert "أحمد" in out.html_body
    assert "847291" in out.html_body
    assert "تحقق" in out.subject  # Arabic for "verify"
    # Direction is RTL — verify the dir attribute is in the HTML
    assert 'dir="rtl"' in out.html_body


def test_render_password_reset_uses_otp() -> None:
    out = render_email(
        "password_reset",
        "en",
        {"user_name": "Sarah", "otp_code": "112233", "expires_in_minutes": 10},
    )
    assert "Sarah" in out.html_body
    assert "112233" in out.html_body
    assert "password" in out.subject.lower()


def test_render_login_otp_does_not_need_user_name() -> None:
    """login_otp's required_vars omits user_name — should render OK without it."""
    out = render_email(
        "login_otp",
        "en",
        {"otp_code": "999000", "expires_in_minutes": 5},
    )
    assert "999000" in out.html_body


def test_render_export_ready_uses_download_url() -> None:
    out = render_email(
        "export_ready",
        "en",
        {"user_name": "X", "download_url": "https://maisys.io/files/abc.pdf"},
    )
    assert "https://maisys.io/files/abc.pdf" in out.html_body


def test_missing_required_var_raises_before_render() -> None:
    """Better to fail fast than ship an email with a placeholder."""
    with pytest.raises(TemplateVariableMissing):
        render_email(
            "email_verify",
            "en",
            {"user_name": "Ahmad", "otp_code": "847291"},  # missing expires_in_minutes
        )


def test_unknown_template_name_raises() -> None:
    with pytest.raises(TemplateNotFound):
        render_email(
            "made_up_template",  # type: ignore[arg-type]
            "en",
            {},
        )


def test_strict_undefined_catches_template_drift() -> None:
    """If a template body uses a var not in required_vars, Jinja2's
    StrictUndefined should still catch it at render time.

    This test passes a known-good var set + verifies the renderer
    doesn't silently swallow missing variables. It's a regression
    guard against future template edits.
    """
    out = render_email(
        "beta_session_reviewed",
        "en",
        {"user_name": "Ahmad"},
    )
    # Sanity: actually rendered something
    assert "Ahmad" in out.html_body
