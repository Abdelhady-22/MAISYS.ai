"""Type definitions for MAISYS authentication."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Role(str, Enum):
    """User roles for RBAC.

    String-valued so the role serializes cleanly into JWT claims and across
    JSON boundaries. Order is conceptual (USER < PREMIUM < ADMIN < SUPER_ADMIN)
    but enforcement is via explicit allowlists in require_role, not via
    ordering — this avoids accidental privilege escalation when adding new
    roles between existing ones.
    """

    USER = "user"
    PREMIUM = "premium"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


class TokenPayload(BaseModel):
    """Validated claim set extracted from a MAISYS-issued JWT.

    Claims:
    - sub: user_id (string-encoded UUID is typical)
    - role: one of the Role enum values
    - exp: epoch seconds — expiration
    - iat: epoch seconds — issued-at
    - iss: issuer string, typically "maisys"
    - jti: token ID; used by services for revocation list lookups
    - scope: optional list of fine-grained permission scopes

    Unknown claims are rejected (extra=forbid) so a token with unexpected
    fields signals a configuration mismatch loudly.
    """

    model_config = ConfigDict(extra="forbid")

    sub: str
    role: Role
    exp: int
    iat: int
    iss: str
    jti: str
    scope: list[str] = Field(default_factory=list)
