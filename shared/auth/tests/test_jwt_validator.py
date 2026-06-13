"""Tests for shared.auth.jwt_validator.decode_token."""

from __future__ import annotations

import time
from typing import cast

import pytest
from jose import jwt

from shared.auth.jwt_validator import decode_token
from shared.auth.types import Role, TokenPayload
from shared.error_handler import AuthenticationException

_TEST_SECRET = "test-secret-do-not-use-in-production-7e3a9c1f"
_TEST_ISSUER = "maisys"


def _make_token(
    *,
    secret: str = _TEST_SECRET,
    sub: str = "user-1",
    role: str = "user",
    exp_offset: int = 3600,
    iat_offset: int = 0,
    iss: str = _TEST_ISSUER,
    jti: str = "j-1",
    extra: dict[str, object] | None = None,
    algorithm: str = "HS256",
) -> str:
    """Build a JWT with the given parameters relative to current time."""
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": sub,
        "role": role,
        "exp": now + exp_offset,
        "iat": now + iat_offset,
        "iss": iss,
        "jti": jti,
    }
    if extra:
        claims.update(extra)
    return cast(str, jwt.encode(claims, secret, algorithm=algorithm))


class TestValidToken:
    def test_returns_payload(self) -> None:
        token = _make_token()
        payload = decode_token(token, _TEST_SECRET)
        assert isinstance(payload, TokenPayload)
        assert payload.sub == "user-1"
        assert payload.role == Role.USER
        assert payload.iss == "maisys"
        assert payload.jti == "j-1"

    def test_with_scope_claim(self) -> None:
        token = _make_token(extra={"scope": ["read:x", "write:y"]})
        payload = decode_token(token, _TEST_SECRET)
        assert payload.scope == ["read:x", "write:y"]

    def test_each_role(self) -> None:
        for role_value in ("user", "premium", "admin", "super_admin"):
            token = _make_token(role=role_value)
            payload = decode_token(token, _TEST_SECRET)
            assert payload.role.value == role_value

    def test_custom_issuer(self) -> None:
        token = _make_token(iss="custom-issuer")
        payload = decode_token(token, _TEST_SECRET, issuer="custom-issuer")
        assert payload.iss == "custom-issuer"


class TestExpired:
    def test_expired_raises(self) -> None:
        token = _make_token(exp_offset=-60)  # 60s in the past
        with pytest.raises(AuthenticationException) as exc_info:
            decode_token(token, _TEST_SECRET)
        assert exc_info.value.code == "TOKEN_EXPIRED"
        assert exc_info.value.status_code == 401


class TestSignature:
    def test_wrong_secret_raises(self) -> None:
        token = _make_token(secret="wrong-secret-aaaaaaaaaaaa")
        with pytest.raises(AuthenticationException) as exc_info:
            decode_token(token, _TEST_SECRET)
        assert exc_info.value.code == "TOKEN_INVALID_SIGNATURE"

    def test_tampered_token_raises(self) -> None:
        token = _make_token()
        # Flip a character in the signature portion
        tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
        with pytest.raises(AuthenticationException) as exc_info:
            decode_token(tampered, _TEST_SECRET)
        assert exc_info.value.code == "TOKEN_INVALID_SIGNATURE"

    def test_garbage_string_raises(self) -> None:
        with pytest.raises(AuthenticationException) as exc_info:
            decode_token("not-even-a-jwt", _TEST_SECRET)
        assert exc_info.value.code == "TOKEN_INVALID_SIGNATURE"

    def test_empty_string_raises(self) -> None:
        with pytest.raises(AuthenticationException):
            decode_token("", _TEST_SECRET)


class TestIssuer:
    def test_wrong_issuer_raises(self) -> None:
        token = _make_token(iss="evil-corp")
        with pytest.raises(AuthenticationException) as exc_info:
            decode_token(token, _TEST_SECRET, issuer="maisys")
        assert exc_info.value.code == "TOKEN_INVALID_ISSUER"


class TestFutureIat:
    def test_iat_within_skew_accepted(self) -> None:
        # 3 seconds in the future — within 5-second skew tolerance
        token = _make_token(iat_offset=3)
        payload = decode_token(token, _TEST_SECRET)
        assert payload.sub == "user-1"

    def test_iat_far_future_rejected(self) -> None:
        # 60 seconds in the future — well beyond skew
        token = _make_token(iat_offset=60)
        with pytest.raises(AuthenticationException) as exc_info:
            decode_token(token, _TEST_SECRET)
        assert exc_info.value.code == "TOKEN_FUTURE_IAT"


class TestMalformedClaims:
    def test_unknown_role_rejected(self) -> None:
        token = _make_token(role="wizard")
        with pytest.raises(AuthenticationException) as exc_info:
            decode_token(token, _TEST_SECRET)
        assert exc_info.value.code == "TOKEN_MALFORMED"

    def test_missing_required_claim_rejected(self) -> None:
        # Build a token that omits `jti` — python-jose signs it fine but
        # TokenPayload validation fails
        now = int(time.time())
        claims = {
            "sub": "user-1",
            "role": "user",
            "exp": now + 3600,
            "iat": now,
            "iss": "maisys",
            # jti missing
        }
        token = jwt.encode(claims, _TEST_SECRET, algorithm="HS256")
        with pytest.raises(AuthenticationException) as exc_info:
            decode_token(token, _TEST_SECRET)
        assert exc_info.value.code == "TOKEN_MALFORMED"

    def test_extra_claim_rejected(self) -> None:
        token = _make_token(extra={"admin_override": True})
        with pytest.raises(AuthenticationException) as exc_info:
            decode_token(token, _TEST_SECRET)
        assert exc_info.value.code == "TOKEN_MALFORMED"
