"""Tests for POST /auth/oauth/{provider}/callback.

We can't use the route's default ``OAuthService`` (which would try to
hit the real Google JWKS endpoint), so we override the route's
dependency to inject a service backed by a mocked httpx client.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import pytest
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from routes.oauth_callback import router
from services.oauth_service import OAuthService


@pytest.fixture(scope="module")
def oauth_keypair() -> dict[str, Any]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pn = private_key.public_key().public_numbers()

    def _b64uint(n: int) -> str:
        import base64

        length = (n.bit_length() + 7) // 8
        return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()

    return {
        "private_pem": private_pem,
        "jwk": {
            "kty": "RSA",
            "alg": "RS256",
            "use": "sig",
            "kid": "route-test-key",
            "n": _b64uint(pn.n),
            "e": _b64uint(pn.e),
        },
    }


def _id_token(keypair: dict[str, Any], *, sub: str, email: str, aud: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "email": email,
            "iss": "https://accounts.google.com",
            "aud": aud,
            "iat": now,
            "exp": now + 3600,
        },
        keypair["private_pem"],
        algorithm="RS256",
        headers={"kid": keypair["jwk"]["kid"]},
    )


def _mock_http(jwk: dict[str, Any]) -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"keys": [jwk]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=5.0)


@pytest.mark.asyncio
async def test_oauth_callback_creates_account(
    db_session: AsyncSession,
    app_for,
    monkeypatch: pytest.MonkeyPatch,
    oauth_keypair: dict[str, Any],
) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "route-test-client")
    id_tok = _id_token(
        oauth_keypair,
        sub="route-new-001",
        email="rnew@example.com",
        aud="route-test-client",
    )
    # Build the app, then monkeypatch the OAuthService constructor so
    # the route gets a service with our injected HTTP client.
    from httpx import ASGITransport, AsyncClient

    mock_client = _mock_http(oauth_keypair["jwk"])
    real_init = OAuthService.__init__

    def patched_init(self, db, http_client=None):  # type: ignore[no-untyped-def]
        real_init(self, db, http_client=mock_client)

    monkeypatch.setattr(OAuthService, "__init__", patched_init)

    app = app_for(router)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/auth/oauth/google/callback",
                json={"id_token": id_tok},
            )
    finally:
        await mock_client.aclose()
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["created"] is True
    assert body["data"]["user"]["email"] == "rnew@example.com"


@pytest.mark.asyncio
async def test_oauth_callback_wrong_audience_returns_400(
    db_session: AsyncSession,
    app_for,
    monkeypatch: pytest.MonkeyPatch,
    oauth_keypair: dict[str, Any],
) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "expected-aud")
    id_tok = _id_token(oauth_keypair, sub="bad-aud-1", email="badaud@example.com", aud="wrong-aud")
    from httpx import ASGITransport, AsyncClient

    mock_client = _mock_http(oauth_keypair["jwk"])
    real_init = OAuthService.__init__
    monkeypatch.setattr(
        OAuthService,
        "__init__",
        lambda self, db, http_client=None: real_init(self, db, http_client=mock_client),
    )

    app = app_for(router)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/auth/oauth/google/callback",
                json={"id_token": id_tok},
            )
    finally:
        await mock_client.aclose()
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "OAUTH_FAILURE"
