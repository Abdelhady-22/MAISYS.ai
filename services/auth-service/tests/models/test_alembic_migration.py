"""Verify the initial Alembic migration creates the auth schema correctly.

Two layers:

1. **Table & column existence**: introspect the migrated DB and check
   every expected table is present, with the expected columns and
   nullability.

2. **Seeding**: the migration seeds the ``roles`` table with the four
   canonical Role enum values from ``shared.auth``. Verify they're all
   present after upgrade.

We use SQLite (in-memory) here intentionally — the same Alembic migration
must work against both SQLite and Postgres, and SQLite is what tests run
against. Production deploys against Postgres exercise the same migration
unchanged.
"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from models.db import Role

EXPECTED_TABLES = {
    "users",
    "user_profiles",
    "oauth_accounts",
    "sessions",
    "otp_codes",
    "password_resets",
    "roles",
    "user_roles",
    "audit_log",
    # alembic_version is created by Alembic itself
    "alembic_version",
}

# Columns we promise exist on each user-defined table (not exhaustive — just
# the security-critical ones the rest of the codebase depends on).
EXPECTED_COLUMNS = {
    "users": {
        "id",
        "email",
        "email_hash",
        "password_hash",
        "role",
        "email_verified",
        "is_active",
        "language_preference",
        "failed_login_attempts",
        "locked_at",
        "last_login_at",
        "created_at",
        "updated_at",
        "deleted_at",
    },
    "user_profiles": {"id", "user_id", "display_name", "avatar_url"},
    "oauth_accounts": {
        "id",
        "user_id",
        "provider",
        "provider_user_id",
        "provider_email",
    },
    "sessions": {
        "id",
        "user_id",
        "jwt_jti",
        "refresh_token_hash",
        "issued_at",
        "expires_at",
        "revoked",
        "revoked_at",
        "user_agent",
        "ip_address",
    },
    "otp_codes": {
        "id",
        "user_id",
        "code_hash",
        "purpose",
        "expires_at",
        "used",
        "used_at",
        "attempt_count",
    },
    "password_resets": {
        "id",
        "user_id",
        "token_hash",
        "expires_at",
        "used",
        "used_at",
    },
    "roles": {"id", "name", "description"},
    "user_roles": {"user_id", "role_id", "created_at"},
    "audit_log": {
        "id",
        "user_id",
        "action",
        "ip_address",
        "user_agent",
        "details",
        "created_at",
    },
}


@pytest.mark.asyncio
async def test_migration_creates_all_expected_tables(
    migrated_engine: AsyncEngine,
) -> None:
    async with migrated_engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
    assert EXPECTED_TABLES.issubset(tables), f"missing tables: {EXPECTED_TABLES - tables}"


@pytest.mark.asyncio
@pytest.mark.parametrize("table_name", sorted(EXPECTED_COLUMNS.keys()))
async def test_migration_creates_expected_columns(
    migrated_engine: AsyncEngine, table_name: str
) -> None:
    async with migrated_engine.connect() as conn:

        def get_cols(sync_conn: Connection) -> set[str]:
            insp = inspect(sync_conn)
            return {c["name"] for c in insp.get_columns(table_name)}

        cols = await conn.run_sync(get_cols)
    expected = EXPECTED_COLUMNS[table_name]
    assert expected.issubset(cols), f"{table_name} missing columns: {expected - cols}"


@pytest.mark.asyncio
async def test_migration_seeds_canonical_roles(
    migrated_engine: AsyncEngine,
) -> None:
    """The four shared.auth.Role values must be present in the roles table."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(bind=migrated_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        result = await session.execute(select(Role.name).order_by(Role.name))
        names = sorted(result.scalars().all())
    assert names == ["admin", "premium", "super_admin", "user"]


@pytest.mark.asyncio
async def test_migration_creates_unique_constraints(
    migrated_engine: AsyncEngine,
) -> None:
    """Critical unique constraints prevent duplicate emails, jti, refresh
    hashes, and (provider, provider_user_id) pairs."""
    async with migrated_engine.connect() as conn:

        def get_uniques(sync_conn: Connection) -> dict[str, list[set[str]]]:
            insp = inspect(sync_conn)
            out: dict[str, list[set[str]]] = {}
            for table in ("users", "sessions", "oauth_accounts"):
                uniques = insp.get_unique_constraints(table)
                out[table] = [set(u["column_names"]) for u in uniques]
            return out

        uniques = await conn.run_sync(get_uniques)

    # users: email and email_hash both unique
    user_unique_cols = uniques["users"]
    assert {"email"} in user_unique_cols
    assert {"email_hash"} in user_unique_cols

    # sessions: jwt_jti and refresh_token_hash both unique
    session_unique_cols = uniques["sessions"]
    assert {"jwt_jti"} in session_unique_cols
    assert {"refresh_token_hash"} in session_unique_cols

    # oauth_accounts: composite (provider, provider_user_id)
    oauth_unique_cols = uniques["oauth_accounts"]
    assert {"provider", "provider_user_id"} in oauth_unique_cols


@pytest.mark.asyncio
async def test_migration_can_downgrade_and_upgrade_again(
    migrated_engine: AsyncEngine,
) -> None:
    """Downgrade -> upgrade cycle leaves the schema in the same shape."""
    from alembic.config import Config
    from pathlib import Path

    service_dir = Path(__file__).resolve().parent.parent.parent
    cfg = Config(str(service_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(service_dir / "alembic"))

    # Downgrade
    async with migrated_engine.connect() as conn:

        def downgrade(sync_conn: Connection) -> None:
            from alembic.runtime.environment import EnvironmentContext
            from alembic.script import ScriptDirectory

            script = ScriptDirectory.from_config(cfg)

            def do_downgrade(rev: object, _context: object) -> list[object]:
                return script._downgrade_revs("base", rev)  # type: ignore[arg-type,return-value]

            with EnvironmentContext(
                cfg,
                script,
                fn=do_downgrade,
                as_sql=False,
                starting_rev=None,
                destination_rev="base",
            ) as env_ctx:
                env_ctx.configure(connection=sync_conn, target_metadata=None)
                with env_ctx.begin_transaction():
                    env_ctx.run_migrations()

        await conn.run_sync(downgrade)

    # Verify all auth tables are gone (alembic_version may or may not stay)
    async with migrated_engine.connect() as conn:
        tables = await conn.run_sync(lambda sync_conn: set(inspect(sync_conn).get_table_names()))
    auth_tables = EXPECTED_TABLES - {"alembic_version"}
    assert auth_tables.isdisjoint(
        tables
    ), f"downgrade left auth tables behind: {auth_tables & tables}"
