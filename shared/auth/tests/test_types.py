"""Tests for shared.auth.types."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from shared.auth.types import Role, TokenPayload


class TestRole:
    def test_string_valued(self) -> None:
        assert Role.USER.value == "user"
        assert Role.PREMIUM.value == "premium"
        assert Role.ADMIN.value == "admin"
        assert Role.SUPER_ADMIN.value == "super_admin"

    def test_str_inheritance(self) -> None:
        # Role inherits from str so it serializes naturally in JSON
        assert Role.ADMIN.value == "admin"
        assert isinstance(Role.ADMIN, str)

    def test_known_values_only(self) -> None:
        # Enums shouldn't accept arbitrary strings
        with pytest.raises(ValueError):
            Role("not_a_role")


class TestTokenPayload:
    def _valid_claims(self) -> dict[str, Any]:
        return {
            "sub": "user-abc-123",
            "role": "user",
            "exp": 1_700_000_100,
            "iat": 1_700_000_000,
            "iss": "maisys",
            "jti": "j-xyz",
        }

    def test_valid_payload(self) -> None:
        p = TokenPayload(**self._valid_claims())
        assert p.sub == "user-abc-123"
        assert p.role == Role.USER
        assert p.exp == 1_700_000_100
        assert p.iat == 1_700_000_000
        assert p.iss == "maisys"
        assert p.jti == "j-xyz"
        assert p.scope == []

    def test_with_scope(self) -> None:
        claims = self._valid_claims()
        claims["scope"] = ["read:profile", "write:profile"]
        p = TokenPayload(**claims)
        assert p.scope == ["read:profile", "write:profile"]

    def test_rejects_unknown_role(self) -> None:
        claims = self._valid_claims()
        claims["role"] = "wizard"
        with pytest.raises(ValidationError):
            TokenPayload(**claims)

    def test_rejects_missing_claim(self) -> None:
        for missing in ("sub", "role", "exp", "iat", "iss", "jti"):
            claims = self._valid_claims()
            del claims[missing]
            with pytest.raises(ValidationError):
                TokenPayload(**claims)

    def test_rejects_extra_claim(self) -> None:
        claims = self._valid_claims()
        claims["nope"] = "extra"
        with pytest.raises(ValidationError):
            TokenPayload(**claims)

    def test_each_role_accepted(self) -> None:
        for role_value in ("user", "premium", "admin", "super_admin"):
            claims = self._valid_claims()
            claims["role"] = role_value
            p = TokenPayload(**claims)
            assert p.role.value == role_value
