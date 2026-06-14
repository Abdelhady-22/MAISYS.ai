"""Tests for OAuthService.

We mock the JWKS endpoint and sign our own ID tokens with a generated
RSA keypair, exercising the full verification + link-or-create path.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import OAuthFailureException
from repository import OAuthAccountRepository, UserRepository
from services.oauth_service import OAuthService


@pytest.fixture(scope="module")
def test_keypair() -> dict[str, Any]:
    """Generate a fresh RSA keypair + JWK form, once per module.

    The PEM goes to ``jwt.encode`` for signing; the JWK goes into the
    mocked JWKS response so ``OAuthService`` can verify our tokens.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_numbers = private_key.public_key().public_numbers()

    def _b64uint(n: int) -> str:
        import base64

        length = (n.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "alg": "RS256",
        "use": "sig",
        "kid": "test-key-1",
        "n": _b64uint(public_numbers.n),
        "e": _b64uint(public_numbers.e),
    }
    return {"private_pem": private_pem, "jwk": jwk}


def _make_id_token(
    keypair: dict[str, Any],
    *,
    sub: str,
    email: str,
    audience: str,
    issuer: str = "https://accounts.google.com",
    expires_in: int = 3600,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": email,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + expires_in,
    }
    return jwt.encode(
        payload,
        keypair["private_pem"],
        algorithm="RS256",
        headers={"kid": keypair["jwk"]["kid"]},
    )


def _mock_jwks_client(jwk: dict[str, Any]) -> httpx.AsyncClient:
    """Return an AsyncClient backed by a MockTransport that serves our JWKS."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": [jwk]})

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport, timeout=5.0)


@pytest.mark.asyncio
async def test_oauth_callback_creates_new_user(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    test_keypair: dict[str, Any],
) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    id_token = _make_id_token(
        test_keypair,
        sub="google-user-001",
        email="newgoogle@example.com",
        audience="test-client-id",
    )
    async with _mock_jwks_client(test_keypair["jwk"]) as http:
        service = OAuthService(db_session, http_client=http)
        result = await service.handle_callback(provider="google", id_token=id_token)
    assert result.created is True
    assert result.user.email == "newgoogle@example.com"
    assert result.user.email_verified is True
    assert result.access_token.count(".") == 2


@pytest.mark.asyncio
async def test_oauth_callback_links_existing_email(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    test_keypair: dict[str, Any],
) -> None:
    """A user with email but no oauth row: callback links the identity."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    users = UserRepository(db_session)
    existing = await users.create(email="exists@example.com", password_hash="hash")
    await users.mark_email_verified(existing.id)
    await db_session.commit()

    id_token = _make_id_token(
        test_keypair,
        sub="google-user-002",
        email="exists@example.com",
        audience="test-client-id",
    )
    async with _mock_jwks_client(test_keypair["jwk"]) as http:
        service = OAuthService(db_session, http_client=http)
        result = await service.handle_callback(provider="google", id_token=id_token)

    assert result.created is False
    assert result.user.id == existing.id
    # An oauth_accounts row now exists for (google, google-user-002)
    oauth_repo = OAuthAccountRepository(db_session)
    linked = await oauth_repo.get_by_provider_and_id("google", "google-user-002")
    assert linked is not None
    assert linked.user_id == existing.id


@pytest.mark.asyncio
async def test_oauth_callback_subsequent_login_uses_oauth_row(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    test_keypair: dict[str, Any],
) -> None:
    """Second callback with same (provider, sub) doesn't create or link
    again — just logs the user in."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    id_token = _make_id_token(
        test_keypair,
        sub="google-user-003",
        email="repeat@example.com",
        audience="test-client-id",
    )
    async with _mock_jwks_client(test_keypair["jwk"]) as http:
        service = OAuthService(db_session, http_client=http)
        # First call — creates the account
        await service.handle_callback(provider="google", id_token=id_token)

    async with _mock_jwks_client(test_keypair["jwk"]) as http:
        service = OAuthService(db_session, http_client=http)
        result2 = await service.handle_callback(provider="google", id_token=id_token)
    assert result2.created is False  # not a new account
    users = UserRepository(db_session)
    user = await users.get_by_email("repeat@example.com")
    assert user is not None
    oauth_repo = OAuthAccountRepository(db_session)
    rows = await oauth_repo.list_for_user(user.id)
    assert len(rows) == 1  # NOT duplicated


@pytest.mark.asyncio
async def test_oauth_callback_wrong_audience_rejected(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    test_keypair: dict[str, Any],
) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "expected-id")
    id_token = _make_id_token(
        test_keypair,
        sub="google-bad-aud",
        email="bad@example.com",
        audience="wrong-id",  # mismatch
    )
    async with _mock_jwks_client(test_keypair["jwk"]) as http:
        service = OAuthService(db_session, http_client=http)
        with pytest.raises(OAuthFailureException):
            await service.handle_callback(provider="google", id_token=id_token)


@pytest.mark.asyncio
async def test_oauth_callback_missing_client_id_rejected(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    test_keypair: dict[str, Any],
) -> None:
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    service = OAuthService(db_session)
    with pytest.raises(OAuthFailureException, match="not configured"):
        await service.handle_callback(provider="google", id_token="any.id.token")
