"""OAuth (Google / Apple) ID-token verification and account linking.

The user completes the OAuth handshake on the client side and posts
the resulting ID token to ``POST /auth/oauth/{provider}/callback``.
We:

1. Fetch the provider's JWKS (cached in the ``httpx`` client).
2. Decode the ID token's header to find the ``kid``.
3. Verify the signature against the matching public key.
4. Verify ``iss``, ``aud``, and expiry claims.
5. Look up an existing ``oauth_accounts`` row for ``(provider, sub)``.
   * Hit → log the user in (issue tokens).
   * Miss → look up by email. If a user with that email exists, link
     the OAuth identity to it; otherwise create a new user (with
     ``email_verified=True`` since the provider has already verified
     the email).
6. Issue access + refresh tokens, persist the session, audit.

Provider configuration via env vars:
* ``GOOGLE_OAUTH_CLIENT_ID`` — required for ``google`` callbacks
* ``APPLE_OAUTH_CLIENT_ID`` — required for ``apple`` callbacks
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions.auth_exceptions import OAuthFailureException
from models.db import User
from repository import (
    AuditRepository,
    OAuthAccountRepository,
    SessionRepository,
    UserRepository,
)
from shared.auth import Role
from utils.jwt import issue_access_token
from utils.tokens import generate_refresh_token, hash_refresh_token

Provider = Literal["google", "apple"]

_PROVIDER_CONFIG: dict[Provider, dict[str, str]] = {
    "google": {
        "jwks_url": "https://www.googleapis.com/oauth2/v3/certs",
        "issuer": "https://accounts.google.com",
        "client_id_env": "GOOGLE_OAUTH_CLIENT_ID",
    },
    "apple": {
        "jwks_url": "https://appleid.apple.com/auth/keys",
        "issuer": "https://appleid.apple.com",
        "client_id_env": "APPLE_OAUTH_CLIENT_ID",
    },
}


@dataclass
class OAuthResult:
    """Output of a successful OAuth callback."""

    access_token: str
    refresh_token: str
    expires_in: int
    user: User
    created: bool


class OAuthService:
    """Verify ID tokens and link/create users."""

    def __init__(
        self,
        db: AsyncSession,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._db = db
        self._users = UserRepository(db)
        self._oauth = OAuthAccountRepository(db)
        self._sessions = SessionRepository(db)
        self._audit = AuditRepository(db)
        self._http = http_client  # Allow injection for tests

    # ── Public entry point ──────────────────────────────────────────
    async def handle_callback(
        self,
        *,
        provider: Provider,
        id_token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_info: str | None = None,
    ) -> OAuthResult:
        cfg = _PROVIDER_CONFIG.get(provider)
        if cfg is None:
            raise OAuthFailureException(f"Unsupported provider: {provider}")

        client_id = os.environ.get(cfg["client_id_env"])
        if not client_id:
            raise OAuthFailureException(f"OAuth provider '{provider}' is not configured")

        claims = await self._verify_id_token(
            id_token=id_token,
            jwks_url=cfg["jwks_url"],
            issuer=cfg["issuer"],
            audience=client_id,
        )
        sub = str(claims.get("sub", ""))
        email_claim = claims.get("email")
        if not sub:
            raise OAuthFailureException("ID token missing 'sub' claim")

        # 1. Existing OAuth link?
        oauth_row = await self._oauth.get_by_provider_and_id(provider, sub)
        if oauth_row is not None:
            user = await self._users.get_by_id(oauth_row.user_id)
            if user is None:
                # Orphaned link — shouldn't happen with CASCADE, but be safe.
                raise OAuthFailureException("Linked account no longer exists")
            return await self._finalise(
                user=user,
                created=False,
                ip_address=ip_address,
                user_agent=user_agent or device_info,
                audit_action="user.oauth.login",
                audit_provider=provider,
            )

        # 2. No OAuth row yet — link by email if user exists, otherwise create.
        email_str = email_claim if isinstance(email_claim, str) and "@" in email_claim else None
        if email_str is None:
            # Apple may omit email on subsequent logins. Without an email
            # AND without an existing oauth_accounts row, we cannot
            # reliably identify the user.
            raise OAuthFailureException(
                "ID token did not carry an email; cannot create or link account"
            )

        user = await self._users.get_by_email(email_str)
        created = False
        if user is None:
            user = await self._users.create(
                email=email_str,
                password_hash=None,  # OAuth-only account
                email_verified=True,  # provider has verified
            )
            created = True

        await self._oauth.create(
            user_id=user.id,
            provider=provider,
            provider_user_id=sub,
            provider_email=email_str,
        )

        return await self._finalise(
            user=user,
            created=created,
            ip_address=ip_address,
            user_agent=user_agent or device_info,
            audit_action="user.oauth.linked" if created else "user.oauth.login",
            audit_provider=provider,
        )

    # ── ID token verification ───────────────────────────────────────
    async def _verify_id_token(
        self,
        *,
        id_token: str,
        jwks_url: str,
        issuer: str,
        audience: str,
    ) -> dict[str, Any]:
        try:
            unverified_header = jwt.get_unverified_header(id_token)
        except Exception as e:
            raise OAuthFailureException("Malformed ID token") from e
        kid = unverified_header.get("kid")
        if not kid:
            raise OAuthFailureException("ID token header missing 'kid'")

        jwks = await self._fetch_jwks(jwks_url)
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
        if key is None:
            raise OAuthFailureException("No matching key in provider JWKS")

        try:
            claims = jwt.decode(
                id_token,
                key,
                algorithms=[key.get("alg", "RS256")],
                audience=audience,
                issuer=issuer,
                options={"verify_at_hash": False},
            )
        except Exception as e:
            raise OAuthFailureException("ID token verification failed") from e
        # The decoded claims are a dict from python-jose — coerce explicitly
        # so mypy sees the right type.
        return dict(claims)

    async def _fetch_jwks(self, url: str) -> dict[str, Any]:
        """Fetch the provider's JWKS. Uses the injected client if any."""
        client = self._http
        owns_client = False
        if client is None:
            client = httpx.AsyncClient(timeout=5.0)
            owns_client = True
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise OAuthFailureException("JWKS response was not a JSON object")
            return data
        except httpx.HTTPError as e:
            raise OAuthFailureException("Could not fetch provider JWKS") from e
        finally:
            if owns_client:
                await client.aclose()

    # ── Token issuance + audit ──────────────────────────────────────
    async def _finalise(
        self,
        *,
        user: User,
        created: bool,
        ip_address: str | None,
        user_agent: str | None,
        audit_action: str,
        audit_provider: Provider,
    ) -> OAuthResult:
        expire_minutes = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
        refresh_days = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

        role = Role(user.role)
        access_token, jti = issue_access_token(str(user.id), role)
        refresh_token = generate_refresh_token()
        now = datetime.now(timezone.utc)
        await self._sessions.create(
            user_id=user.id,
            jwt_jti=jti,
            refresh_token_hash=hash_refresh_token(refresh_token),
            issued_at=now,
            expires_at=now + timedelta(days=refresh_days),
            user_agent=user_agent,
            ip_address=ip_address,
        )
        await self._users.update_last_login(user.id)
        await self._audit.log(
            action=audit_action,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={"provider": audit_provider, "created_account": created},
        )
        await self._db.commit()
        await self._db.refresh(user)
        return OAuthResult(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expire_minutes * 60,
            user=user,
            created=created,
        )


__all__ = ["OAuthResult", "OAuthService", "Provider"]
