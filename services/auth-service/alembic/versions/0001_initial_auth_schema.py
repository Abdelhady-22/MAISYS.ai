"""initial auth schema

Revision ID: 0001_initial_auth_schema
Revises:
Create Date: 2026-06-14 00:00:00.000000

Creates the nine auth-service tables (users, user_profiles, oauth_accounts,
sessions, otp_codes, password_resets, roles, user_roles, audit_log) and
seeds the roles catalogue with the four canonical Role enum values from
shared.auth.

Cross-dialect notes:
* ``sa.Uuid`` works on both Postgres (native UUID) and SQLite (TEXT).
* ``sa.JSON`` maps to JSONB on Postgres and TEXT on SQLite.
* ``DateTime(timezone=True)`` becomes TIMESTAMPTZ on Postgres and TEXT on
  SQLite — values round-trip as tz-aware datetimes either way.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0001_initial_auth_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("email_hash", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "language_preference",
            sa.String(length=5),
            nullable=False,
            server_default="en",
        ),
        sa.Column(
            "failed_login_attempts",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.UniqueConstraint("email_hash", name="uq_users_email_hash"),
    )
    op.create_index("idx_users_email_hash", "users", ["email_hash"])
    op.create_index("idx_users_role", "users", ["role"])
    op.create_index("idx_users_created_at", "users", ["created_at"])

    # ── user_profiles ────────────────────────────────────────────────
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("avatar_url", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
    )

    # ── oauth_accounts ───────────────────────────────────────────────
    op.create_table(
        "oauth_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("provider_email", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_user"),
    )
    op.create_index("idx_oauth_user_id", "oauth_accounts", ["user_id"])
    op.create_index(
        "idx_oauth_provider_user",
        "oauth_accounts",
        ["provider", "provider_user_id"],
    )

    # ── sessions ─────────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("jwt_jti", sa.String(length=36), nullable=False),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("jwt_jti", name="uq_sessions_jwt_jti"),
        sa.UniqueConstraint("refresh_token_hash", name="uq_sessions_refresh_hash"),
    )
    op.create_index("idx_sessions_user_id", "sessions", ["user_id"])
    op.create_index("idx_sessions_jwt_jti", "sessions", ["jwt_jti"])
    op.create_index("idx_sessions_refresh_hash", "sessions", ["refresh_token_hash"])
    op.create_index("idx_sessions_expires_at", "sessions", ["expires_at"])

    # ── otp_codes ────────────────────────────────────────────────────
    op.create_table(
        "otp_codes",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempt_count",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "idx_otp_user_purpose",
        "otp_codes",
        ["user_id", "purpose", "used", "expires_at"],
    )

    # ── password_resets ──────────────────────────────────────────────
    op.create_table(
        "password_resets",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_password_resets_token_hash"),
    )
    op.create_index("idx_password_resets_user_id", "password_resets", ["user_id"])
    op.create_index("idx_password_resets_token_hash", "password_resets", ["token_hash"])

    # ── roles ────────────────────────────────────────────────────────
    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    op.create_index("idx_roles_name", "roles", ["name"])

    # Seed canonical roles. Names match shared.auth.Role enum values.
    # Mass-insert via op.bulk_insert so the migration is dialect-agnostic.
    roles_table = sa.table(
        "roles",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
    )
    import uuid as _uuid

    op.bulk_insert(
        roles_table,
        [
            {
                "id": _uuid.uuid4(),
                "name": "user",
                "description": "Default end-user role",
            },
            {
                "id": _uuid.uuid4(),
                "name": "premium",
                "description": "Paid premium user",
            },
            {
                "id": _uuid.uuid4(),
                "name": "admin",
                "description": "Service administrator",
            },
            {
                "id": _uuid.uuid4(),
                "name": "super_admin",
                "description": "Platform super-administrator",
            },
        ],
    )

    # ── user_roles ───────────────────────────────────────────────────
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    # ── audit_log ────────────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("idx_audit_log_user_id", "audit_log", ["user_id"])
    op.create_index("idx_audit_log_action", "audit_log", ["action"])
    op.create_index("idx_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    # Reverse order so dependent tables drop before their referents.
    op.drop_index("idx_audit_log_created_at", table_name="audit_log")
    op.drop_index("idx_audit_log_action", table_name="audit_log")
    op.drop_index("idx_audit_log_user_id", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_table("user_roles")

    op.drop_index("idx_roles_name", table_name="roles")
    op.drop_table("roles")

    op.drop_index("idx_password_resets_token_hash", table_name="password_resets")
    op.drop_index("idx_password_resets_user_id", table_name="password_resets")
    op.drop_table("password_resets")

    op.drop_index("idx_otp_user_purpose", table_name="otp_codes")
    op.drop_table("otp_codes")

    op.drop_index("idx_sessions_expires_at", table_name="sessions")
    op.drop_index("idx_sessions_refresh_hash", table_name="sessions")
    op.drop_index("idx_sessions_jwt_jti", table_name="sessions")
    op.drop_index("idx_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("idx_oauth_provider_user", table_name="oauth_accounts")
    op.drop_index("idx_oauth_user_id", table_name="oauth_accounts")
    op.drop_table("oauth_accounts")

    op.drop_table("user_profiles")

    op.drop_index("idx_users_created_at", table_name="users")
    op.drop_index("idx_users_role", table_name="users")
    op.drop_index("idx_users_email_hash", table_name="users")
    op.drop_table("users")
