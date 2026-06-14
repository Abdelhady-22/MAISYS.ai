"""Tests for utils.jwt (HS256 access-token issuance).

The most important assertion here is that tokens we issue can be decoded
by the canonical ``shared.auth.decode_token`` — this is the contract
every other MAISYS service validates against.
"""

from __future__ import annotations

import time
from uuid import uuid4

import pytest
from jose import jwt as jose_jwt

from shared.auth import Role, decode_token
from utils.jwt import issue_access_token


def test_issue_access_token_returns_token_and_jti() -> None:
    user_id = str(uuid4())
    token, jti = issue_access_token(user_id, Role.USER)

    # Token is a non-empty string
    assert isinstance(token, str) and token.count(".") == 2
    # jti is a UUID string
    assert isinstance(jti, str) and len(jti) == 36


def test_issued_token_roundtrips_through_shared_decoder() -> None:
    """The canonical interop test — every service uses decode_token."""
    import os

    user_id = str(uuid4())
    token, jti = issue_access_token(user_id, Role.PREMIUM, scope=["read"])

    payload = decode_token(token, secret=os.environ["JWT_SECRET"])
    assert payload.sub == user_id
    assert payload.role == Role.PREMIUM
    assert payload.iss == "maisys"
    assert payload.jti == jti
    assert payload.scope == ["read"]
    # iat/exp are integers within reasonable bounds
    assert payload.exp > payload.iat
    assert payload.iat <= int(time.time()) + 5  # 5s skew tolerance


def test_default_scope_is_empty_list() -> None:
    """When the caller doesn't pass scope, the claim must be [] not omitted."""
    token, _ = issue_access_token(str(uuid4()), Role.USER)
    # Decode raw with python-jose to inspect the claim shape directly.
    import os

    raw = jose_jwt.decode(
        token,
        os.environ["JWT_SECRET"],
        algorithms=["HS256"],
        # Skip our extra-claims validation here; we want to see the raw shape.
        options={"verify_signature": True},
    )
    assert raw["scope"] == []


def test_missing_jwt_secret_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        issue_access_token(str(uuid4()), Role.USER)


def test_invalid_expire_minutes_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "not-a-number")
    with pytest.raises(RuntimeError, match="ACCESS_TOKEN_EXPIRE_MINUTES"):
        issue_access_token(str(uuid4()), Role.USER)


def test_jti_unique_across_calls() -> None:
    """Each issuance must generate a fresh jti so refresh rotation works."""
    _, jti_a = issue_access_token(str(uuid4()), Role.USER)
    _, jti_b = issue_access_token(str(uuid4()), Role.USER)
    assert jti_a != jti_b


def test_token_uses_hs256_algorithm() -> None:
    """The shared decoder only accepts HS256; we must issue HS256."""
    token, _ = issue_access_token(str(uuid4()), Role.USER)
    header = jose_jwt.get_unverified_header(token)
    assert header["alg"] == "HS256"
