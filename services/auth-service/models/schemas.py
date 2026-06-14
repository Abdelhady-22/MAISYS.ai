"""Pydantic request/response schemas for every auth-service endpoint.

Every schema uses ``model_config = ConfigDict(extra="forbid")`` so
unexpected fields in either direction are rejected loudly — a corruption-
or-config bug catches before it reaches business logic.

Password validation enforces the rules in part5.md §6.2:
- min 8 chars, max 128 chars
- at least one uppercase, one lowercase, one digit

JWT token payloads are NOT defined here — they live in
``shared.auth.types.TokenPayload``, which is the canonical contract every
other service validates against.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from shared.auth import Role
from shared.models import ISOLanguageCode

# ──────────────────────────────────────────────────────────────────────────
# Password validation
# ──────────────────────────────────────────────────────────────────────────

_UPPERCASE = re.compile(r"[A-Z]")
_LOWERCASE = re.compile(r"[a-z]")
_DIGIT = re.compile(r"[0-9]")


def _validate_password(value: str) -> str:
    """Apply MAISYS password rules: ≥8 chars, ≤128, upper+lower+digit.

    Raises ValueError on failure — Pydantic surfaces it as a 422 with a
    structured ``loc``/``msg`` so the client sees which field failed.
    """
    if not isinstance(value, str):
        raise ValueError("password must be a string")
    if len(value) < 8:
        raise ValueError("password must be at least 8 characters")
    if len(value) > 128:
        raise ValueError("password must be at most 128 characters")
    if not _UPPERCASE.search(value):
        raise ValueError("password must contain at least one uppercase letter")
    if not _LOWERCASE.search(value):
        raise ValueError("password must contain at least one lowercase letter")
    if not _DIGIT.search(value):
        raise ValueError("password must contain at least one digit")
    return value


# ──────────────────────────────────────────────────────────────────────────
# Shared / response building blocks
# ──────────────────────────────────────────────────────────────────────────


class UserPublic(BaseModel):
    """Public-safe projection of a User. Never includes password_hash."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    email: EmailStr
    role: Role
    email_verified: bool
    language_preference: ISOLanguageCode


class TokenPair(BaseModel):
    """Issued access + refresh tokens, plus expiry hint for clients."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int = Field(
        description="Access token TTL in seconds (per ACCESS_TOKEN_EXPIRE_MINUTES env)."
    )


class SessionInfo(BaseModel):
    """One row of GET /auth/sessions response."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    issued_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip_address: str | None
    revoked: bool


# ──────────────────────────────────────────────────────────────────────────
# POST /auth/register
# ──────────────────────────────────────────────────────────────────────────


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str
    language_preference: ISOLanguageCode = "en"

    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return _validate_password(v)


class RegisterResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    email: EmailStr
    message: str


# ──────────────────────────────────────────────────────────────────────────
# POST /auth/verify-otp
# ──────────────────────────────────────────────────────────────────────────


OTPPurpose = Literal["email_verify", "password_reset", "login_otp"]


class VerifyOTPRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    purpose: OTPPurpose


class VerifyOTPResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verified: bool
    message: str


# ──────────────────────────────────────────────────────────────────────────
# POST /auth/login
# ──────────────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    device_info: str | None = Field(default=None, max_length=512)


class LoginResponse(BaseModel):
    """Successful login — tokens issued, user payload included.

    A separate ``OTPRequiredResponse`` covers the OTP-needed branch; the
    route returns one of the two via ``response_model=LoginResponse |
    OTPRequiredResponse``.
    """

    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    user: UserPublic


class OTPRequiredResponse(BaseModel):
    """Login succeeded but requires OTP completion."""

    model_config = ConfigDict(extra="forbid")

    otp_required: Literal[True] = True
    otp_token: UUID
    message: str


# ──────────────────────────────────────────────────────────────────────────
# POST /auth/oauth/{provider}/callback
# ──────────────────────────────────────────────────────────────────────────


OAuthProvider = Literal["google", "apple"]


class OAuthCallbackRequest(BaseModel):
    """Body for OAuth callback. The provider goes in the URL path; here
    we accept the ID token from the client (the client did the front-end
    redirect handshake)."""

    model_config = ConfigDict(extra="forbid")

    id_token: str = Field(min_length=1)
    device_info: str | None = Field(default=None, max_length=512)


class OAuthCallbackResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int
    user: UserPublic
    created: bool = Field(description="True if a new user was created; False if this was a login.")


# ──────────────────────────────────────────────────────────────────────────
# POST /auth/refresh
# ──────────────────────────────────────────────────────────────────────────


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1)


class RefreshResponse(BaseModel):
    """New token pair after rotation. Old refresh token is now revoked."""

    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int


# ──────────────────────────────────────────────────────────────────────────
# POST /auth/logout
# ──────────────────────────────────────────────────────────────────────────


class LogoutRequest(BaseModel):
    """Logout revokes the refresh token. Caller is the bearer of the
    access token (Authorization header); we use the access token's jti
    to find the session, and revoke it."""

    model_config = ConfigDict(extra="forbid")


class LogoutResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = "Logged out"


# ──────────────────────────────────────────────────────────────────────────
# POST /auth/password/reset/request
# ──────────────────────────────────────────────────────────────────────────


class PasswordResetRequestRequest(BaseModel):
    """A reset request always returns 200, even for unknown emails (per
    task spec — no email enumeration). The schema is therefore minimal."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class PasswordResetRequestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = "If that email is registered, a reset link has been sent."


# ──────────────────────────────────────────────────────────────────────────
# POST /auth/password/reset/confirm
# ──────────────────────────────────────────────────────────────────────────


class PasswordResetConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return _validate_password(v)


class PasswordResetConfirmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = "Password updated. Please log in with your new password."


# ──────────────────────────────────────────────────────────────────────────
# GET /auth/me  +  PATCH /auth/me
# ──────────────────────────────────────────────────────────────────────────


class MeResponse(BaseModel):
    """Full profile of the authenticated user."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    email: EmailStr
    role: Role
    email_verified: bool
    is_active: bool
    language_preference: ISOLanguageCode
    display_name: str | None
    avatar_url: str | None
    created_at: datetime
    last_login_at: datetime | None


class UpdateProfileRequest(BaseModel):
    """Patch only the fields the user wants to change. Missing fields are
    left alone.

    Email changes go through a re-verification flow (issuing a new OTP);
    the route handles that. The client cannot patch ``role`` or
    ``is_active`` from this endpoint — those are admin-only.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    display_name: str | None = Field(default=None, max_length=100)
    avatar_url: str | None = Field(default=None, max_length=512)
    language_preference: ISOLanguageCode | None = None


class UpdateProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: MeResponse
    email_reverification_required: bool = False
    message: str | None = None


# ──────────────────────────────────────────────────────────────────────────
# GET /auth/sessions  +  DELETE /auth/sessions/{id}
# ──────────────────────────────────────────────────────────────────────────


class SessionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions: list[SessionInfo]


class DeleteSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = "Session revoked"


__all__ = [
    "DeleteSessionResponse",
    "LoginRequest",
    "LoginResponse",
    "LogoutRequest",
    "LogoutResponse",
    "MeResponse",
    "OAuthCallbackRequest",
    "OAuthCallbackResponse",
    "OAuthProvider",
    "OTPPurpose",
    "OTPRequiredResponse",
    "PasswordResetConfirmRequest",
    "PasswordResetConfirmResponse",
    "PasswordResetRequestRequest",
    "PasswordResetRequestResponse",
    "RefreshRequest",
    "RefreshResponse",
    "RegisterRequest",
    "RegisterResponse",
    "SessionInfo",
    "SessionListResponse",
    "TokenPair",
    "UpdateProfileRequest",
    "UpdateProfileResponse",
    "UserPublic",
    "VerifyOTPRequest",
    "VerifyOTPResponse",
]
