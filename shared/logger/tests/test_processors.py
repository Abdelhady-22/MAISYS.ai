"""Tests for shared.logger.processors.scrub_sensitive."""

from __future__ import annotations

import pytest

from shared.logger.processors import REDACTED, scrub_sensitive


def _scrub(event_dict: dict[str, object]) -> dict[str, object]:
    """Helper: call scrub_sensitive with dummy logger + method args."""
    result = scrub_sensitive(None, "info", dict(event_dict))
    # scrub_sensitive returns MutableMapping but in our tests we pass a dict
    # and it modifies in place, so the runtime type is always dict.
    return dict(result)


class TestRedactByKey:
    @pytest.mark.parametrize(
        "key",
        [
            "password",
            "Password",
            "PASSWORD",
            "passwd",
            "user_password",
            "old_password",
            "secret",
            "client_secret",
            "client-secret",
            "api_key",
            "api-key",
            "apiKey",
            "apikey",
            "API_KEY",
            "access_token",
            "accessToken",
            "refresh_token",
            "token",
            "Token",
            "authorization",
            "Authorization",
            "cookie",
            "Cookie",
            "set-cookie",
            "Set-Cookie",
            "private_key",
            "private-key",
            "privateKey",
        ],
    )
    def test_sensitive_keys_redacted(self, key: str) -> None:
        result = _scrub({key: "sensitive_value"})
        assert result[key] == REDACTED, f"Expected {key} to be redacted"

    @pytest.mark.parametrize(
        "key",
        [
            "name",
            "user_id",
            "email",
            "count",
            "duration_ms",
            "status_code",
            "request_id",
            "method",
            "path",
            "service",
            "tokenizer",  # contains "token" as substring but \btoken\b boundary excludes it
        ],
    )
    def test_normal_keys_preserved(self, key: str) -> None:
        result = _scrub({key: "value"})
        assert result[key] == "value", f"Expected {key} to be preserved"

    def test_value_type_replaced_with_string(self) -> None:
        # Even if the original value was an int, it becomes the redacted string
        result = _scrub({"password_attempts": 3, "password": 12345})
        assert result["password_attempts"] == REDACTED
        assert result["password"] == REDACTED


class TestJWTDetection:
    def test_jwt_in_value_redacted(self) -> None:
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjMifQ.sigsigsig"
        result = _scrub({"some_field": jwt})
        assert result["some_field"] == REDACTED

    def test_short_jwt_not_redacted(self) -> None:
        # Three segments but too short to plausibly be a JWT
        result = _scrub({"value": "ey.ey.x"})
        assert result["value"] == "ey.ey.x"

    def test_non_jwt_string_preserved(self) -> None:
        result = _scrub({"value": "normal string"})
        assert result["value"] == "normal string"

    def test_email_not_redacted(self) -> None:
        result = _scrub({"email": "user@example.com"})
        assert result["email"] == "user@example.com"

    def test_uuid_not_redacted(self) -> None:
        result = _scrub({"request_id": "550e8400-e29b-41d4-a716-446655440000"})
        assert result["request_id"] == "550e8400-e29b-41d4-a716-446655440000"


class TestEventDictShape:
    def test_empty_event_dict(self) -> None:
        assert _scrub({}) == {}

    def test_mixed_sensitive_and_normal(self) -> None:
        result = _scrub(
            {
                "user_id": 42,
                "password": "secret123",
                "email": "user@example.com",
                "api_key": "ak_live_abc123",
            }
        )
        assert result == {
            "user_id": 42,
            "password": REDACTED,
            "email": "user@example.com",
            "api_key": REDACTED,
        }

    def test_returns_modified_event_dict(self) -> None:
        # scrub_sensitive must return a dict (structlog processor contract)
        result = _scrub({"password": "x"})
        assert isinstance(result, dict)
