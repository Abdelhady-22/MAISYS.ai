"""SQLAlchemy 2.0 ORM models for auth-service.

All models inherit from ``shared.models.Base`` and use the shared mixins
(``UUIDMixin``, ``TimestampMixin``, ``SoftDeleteMixin``). Column types
use SQLAlchemy 2.0's generic types so the same models work against
PostgreSQL in production and SQLite (via aiosqlite) in unit tests:

* ``Uuid`` — Postgres UUID, SQLite TEXT (UUID stored as 32-char hex)
* ``JSON`` — Postgres JSONB, SQLite TEXT
* ``DateTime(timezone=True)`` — TIMESTAMPTZ on Postgres, TEXT on SQLite

Schema references: see ``/docs/technical-guides/part5.md`` §1.1 (auth
schemas) and the auth-service spec in part5.md §6. Conflicts between the
task spec and part5.md are documented in PROGRESS.md Clarifications Log.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.models import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin


class User(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Account record. Source of truth for identity.

    ``password_hash`` is nullable because OAuth-only accounts never set a
    password. ``email_hash`` is a SHA-256 hex of the lowercase email, used
    by ``UserRepository.get_by_email_hash`` for indexed lookups without
    decrypting the email column (if it's ever encrypted at rest).

    ``role`` is a quick-access denormalisation of the user's primary role.
    The full normalised many-to-many lives in ``user_roles`` for future
    fine-grained RBAC; for now both are kept in sync by the repository.
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    language_preference: Mapped[str] = mapped_column(String(5), nullable=False, default="en")
    failed_login_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    profile: Mapped["UserProfile | None"] = relationship(
        "UserProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    oauth_accounts: Mapped[list["OAuthAccount"]] = relationship(
        "OAuthAccount",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[list["Session"]] = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    otp_codes: Mapped[list["OTPCode"]] = relationship(
        "OTPCode",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    password_resets: Mapped[list["PasswordReset"]] = relationship(
        "PasswordReset",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    user_roles: Mapped[list["UserRole"]] = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_users_email_hash", "email_hash"),
        Index("idx_users_role", "role"),
        Index("idx_users_created_at", "created_at"),
    )


class UserProfile(Base, UUIDMixin, TimestampMixin):
    """One-to-one profile data: display name, avatar.

    Kept separate from ``users`` so account changes (password, role, lock
    state) don't churn the same row as cosmetic profile updates. The
    ``user_id`` UNIQUE constraint enforces the one-to-one shape at the
    schema level (a UNIQUE FK is the canonical SQL idiom).
    """

    __tablename__ = "user_profiles"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="profile")


class OAuthAccount(Base, UUIDMixin, TimestampMixin):
    """A link between a User and an external OAuth identity (Google/Apple).

    A single User may have multiple OAuthAccount rows (one per provider).
    ``provider_user_id`` is the provider's stable subject claim, paired
    with ``provider`` as a unique constraint — re-linking is allowed
    against the same user but the same (provider, sub) pair cannot map
    to two MAISYS users.
    """

    __tablename__ = "oauth_accounts"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="oauth_accounts")

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
        Index("idx_oauth_user_id", "user_id"),
        Index("idx_oauth_provider_user", "provider", "provider_user_id"),
    )


class Session(Base, UUIDMixin, TimestampMixin):
    """Active session: JWT jti + refresh token hash + tracking metadata.

    Per Clarifications Log C3 (PROGRESS.md): we keep both jwt_jti and
    refresh_token_hash on this single ``sessions`` table rather than
    splitting refresh tokens into a separate table (part5.md models them
    separately). One Session = one refresh-token-lifetime; refresh
    rotation revokes the current row and creates a new one.
    """

    __tablename__ = "sessions"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    jwt_jti: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)
    refresh_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="sessions")

    __table_args__ = (
        Index("idx_sessions_user_id", "user_id"),
        Index("idx_sessions_jwt_jti", "jwt_jti"),
        Index("idx_sessions_refresh_hash", "refresh_token_hash"),
        Index("idx_sessions_expires_at", "expires_at"),
    )


class OTPCode(Base, UUIDMixin, TimestampMixin):
    """A 6-digit one-time code for email verification / login OTP.

    The raw code is never stored — only the SHA-256 hash (per
    Clarifications Log C10: part5.md §1.1 says VARCHAR(64) which matches
    SHA-256 hex; §6.3 says bcrypt; we resolved in favour of §1.1).

    ``purpose`` segregates use cases so an ``email_verify`` OTP cannot be
    accepted on a ``password_reset`` flow.
    """

    __tablename__ = "otp_codes"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(String(30), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)

    user: Mapped[User] = relationship("User", back_populates="otp_codes")

    __table_args__ = (Index("idx_otp_user_purpose", "user_id", "purpose", "used", "expires_at"),)


class PasswordReset(Base, UUIDMixin, TimestampMixin):
    """A single-use, time-limited password reset token.

    Stored as SHA-256 hash; the raw token goes to the user via email and
    is sent back on ``/auth/password/reset/confirm``. ``used`` enforces
    single-use semantics — a token is invalidated after one successful
    reset.
    """

    __tablename__ = "password_resets"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="password_resets")

    __table_args__ = (
        Index("idx_password_resets_user_id", "user_id"),
        Index("idx_password_resets_token_hash", "token_hash"),
    )


class Role(Base, UUIDMixin, TimestampMixin):
    """Normalised role catalogue.

    Seeded by the initial Alembic migration with the four roles defined
    in ``shared.auth.Role`` (user, premium, admin, super_admin). The
    ``users.role`` column is the fast-access denormalisation; the
    normalised assignment lives in ``user_roles`` for future
    multi-role RBAC.
    """

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user_roles: Mapped[list["UserRole"]] = relationship(
        "UserRole",
        back_populates="role",
        cascade="all, delete-orphan",
    )

    __table_args__ = (Index("idx_roles_name", "name"),)


class UserRole(Base):
    """Many-to-many user ↔ role assignment.

    Composite primary key (user_id, role_id). No UUIDMixin here — the
    natural key IS the composite. ``created_at`` is present for audit
    purposes but no ``updated_at`` (assignments are immutable; to change a
    role, delete and re-insert).
    """

    __tablename__ = "user_roles"

    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    user: Mapped[User] = relationship("User", back_populates="user_roles")
    role: Mapped[Role] = relationship("Role", back_populates="user_roles")


class AuditLog(Base, UUIDMixin):
    """Immutable record of sensitive events.

    No UpdateAt — once written, rows are append-only. ``user_id`` is
    nullable because pre-login events (e.g. failed registration on a
    duplicate email) have no authenticated user. ``details`` is a JSONB
    column carrying event-specific structured context (action-specific
    payload; see the route layer for the schema per action).
    """

    __tablename__ = "audit_log"

    user_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_audit_log_user_id", "user_id"),
        Index("idx_audit_log_action", "action"),
        Index("idx_audit_log_created_at", "created_at"),
    )


__all__ = [
    "AuditLog",
    "OAuthAccount",
    "OTPCode",
    "PasswordReset",
    "Role",
    "Session",
    "User",
    "UserProfile",
    "UserRole",
]
