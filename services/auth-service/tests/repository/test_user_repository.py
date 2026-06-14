"""Tests for UserRepository against in-memory SQLite."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from repository.user_repository import UserRepository, _hash_email


@pytest.mark.asyncio
async def test_create_user_persists_email_and_hash(
    db_session: AsyncSession,
) -> None:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="Alice@Example.com",
        password_hash="argon2$dummy",
        language_preference="en",
    )
    # Email is normalised to lowercase
    assert user.email == "alice@example.com"
    # email_hash is SHA-256 of lowercase email
    assert user.email_hash == _hash_email("alice@example.com")
    # Defaults are applied
    assert user.role == "user"
    assert user.email_verified is False
    assert user.is_active is True
    assert user.failed_login_attempts == 0


@pytest.mark.asyncio
async def test_create_user_creates_profile_row(
    db_session: AsyncSession,
) -> None:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="bob@example.com",
        password_hash="hash",
        display_name="Bobbity",
    )
    # Profile was created and linked
    await db_session.refresh(user, ["profile"])
    assert user.profile is not None
    assert user.profile.display_name == "Bobbity"


@pytest.mark.asyncio
async def test_get_by_email_case_insensitive(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    await repo.create(email="Carol@example.com", password_hash="h")
    await db_session.commit()

    # Case + whitespace don't matter — both forms hash to the same key.
    fetched = await repo.get_by_email("  CAROL@example.com  ")
    assert fetched is not None
    assert fetched.email == "carol@example.com"


@pytest.mark.asyncio
async def test_get_by_email_returns_none_for_unknown(
    db_session: AsyncSession,
) -> None:
    repo = UserRepository(db_session)
    assert await repo.get_by_email("nobody@example.com") is None


@pytest.mark.asyncio
async def test_get_by_email_hash_direct_lookup(
    db_session: AsyncSession,
) -> None:
    repo = UserRepository(db_session)
    user = await repo.create(email="dave@example.com", password_hash="h")
    await db_session.commit()
    fetched = await repo.get_by_email_hash(user.email_hash)
    assert fetched is not None
    assert fetched.id == user.id


@pytest.mark.asyncio
async def test_get_by_id_filters_soft_deleted_by_default(
    db_session: AsyncSession,
) -> None:
    repo = UserRepository(db_session)
    user = await repo.create(email="eve@example.com", password_hash="h")
    await repo.soft_delete(user.id)
    await db_session.commit()

    # Default: soft-deleted users are invisible
    assert await repo.get_by_id(user.id) is None
    # Explicit opt-in: include_deleted=True returns the row
    again = await repo.get_by_id(user.id, include_deleted=True)
    assert again is not None
    assert again.deleted_at is not None


@pytest.mark.asyncio
async def test_mark_email_verified(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    user = await repo.create(email="f@example.com", password_hash="h")
    assert user.email_verified is False
    await repo.mark_email_verified(user.id)
    await db_session.commit()
    fetched = await repo.get_by_id(user.id)
    assert fetched is not None
    assert fetched.email_verified is True


@pytest.mark.asyncio
async def test_update_password(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    user = await repo.create(email="g@example.com", password_hash="old")
    await repo.update_password(user.id, "new")
    await db_session.commit()
    fetched = await repo.get_by_id(user.id)
    assert fetched is not None
    assert fetched.password_hash == "new"


@pytest.mark.asyncio
async def test_update_last_login_resets_failed_attempts(
    db_session: AsyncSession,
) -> None:
    """A successful login resets the failed-login counter and unlocks."""
    repo = UserRepository(db_session)
    user = await repo.create(email="h@example.com", password_hash="h")
    # Simulate prior failures
    await repo.increment_failed_logins(user.id)
    await repo.increment_failed_logins(user.id)
    await repo.lock_account(user.id)
    await db_session.commit()

    await repo.update_last_login(user.id)
    await db_session.commit()
    fetched = await repo.get_by_id(user.id)
    assert fetched is not None
    assert fetched.failed_login_attempts == 0
    assert fetched.locked_at is None
    assert fetched.last_login_at is not None


@pytest.mark.asyncio
async def test_update_email_changes_hash_and_clears_verified(
    db_session: AsyncSession,
) -> None:
    repo = UserRepository(db_session)
    user = await repo.create(email="i@example.com", password_hash="h", email_verified=False)
    await repo.mark_email_verified(user.id)
    await db_session.commit()

    await repo.update_email(user.id, "i_NEW@example.com")
    await db_session.commit()
    fetched = await repo.get_by_id(user.id)
    assert fetched is not None
    assert fetched.email == "i_new@example.com"
    assert fetched.email_hash == _hash_email("i_new@example.com")
    # Email change must clear verification
    assert fetched.email_verified is False


@pytest.mark.asyncio
async def test_increment_failed_logins_returns_new_count(
    db_session: AsyncSession,
) -> None:
    repo = UserRepository(db_session)
    user = await repo.create(email="j@example.com", password_hash="h")
    assert await repo.increment_failed_logins(user.id) == 1
    assert await repo.increment_failed_logins(user.id) == 2
    assert await repo.increment_failed_logins(user.id) == 3


@pytest.mark.asyncio
async def test_lock_and_unlock_account(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    user = await repo.create(email="k@example.com", password_hash="h")
    await repo.lock_account(user.id)
    await db_session.commit()
    fetched = await repo.get_by_id(user.id)
    assert fetched is not None
    assert fetched.locked_at is not None

    await repo.unlock_account(user.id)
    await db_session.commit()
    fetched = await repo.get_by_id(user.id)
    assert fetched is not None
    assert fetched.locked_at is None


@pytest.mark.asyncio
async def test_update_profile_patches_only_provided_fields(
    db_session: AsyncSession,
) -> None:
    repo = UserRepository(db_session)
    user = await repo.create(
        email="l@example.com",
        password_hash="h",
        display_name="Original",
    )
    await db_session.commit()

    # Patch display_name only — avatar_url is left alone.
    await repo.update_profile(user.id, display_name="Updated")
    await db_session.commit()
    await db_session.refresh(user, ["profile"])
    assert user.profile is not None
    assert user.profile.display_name == "Updated"
    assert user.profile.avatar_url is None

    # Patch language_preference (lives on users, not profile)
    await repo.update_profile(user.id, language_preference="ar")
    await db_session.commit()
    fetched = await repo.get_by_id(user.id)
    assert fetched is not None
    assert fetched.language_preference == "ar"
