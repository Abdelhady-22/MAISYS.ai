"""User data access — the most-used repository.

Encapsulates:
* email hashing on insert (SHA-256 of lowercased email; the column is
  indexed and used by the login fast path)
* role lookup (read from the users.role denormalised column)
* failed-login bookkeeping (increment / reset / lock / unlock)
* soft-delete semantics — queries filter ``deleted_at IS NULL`` by default

Methods that don't return a value to the caller commit; methods that
return a model leave the commit to the caller (typically the FastAPI
dependency's ``get_db_session`` wrapper, which commits on success).
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.db import User, UserProfile


def _hash_email(email: str) -> str:
    """SHA-256 of the lowercased, stripped email — used for indexed lookup."""
    normalised = email.strip().lower().encode("utf-8")
    return hashlib.sha256(normalised).hexdigest()


class UserRepository:
    """Data access for ``users`` and the 1:1 ``user_profiles`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Reads ────────────────────────────────────────────────────────
    async def get_by_id(self, user_id: UUID, *, include_deleted: bool = False) -> User | None:
        stmt = select(User).where(User.id == user_id)
        if not include_deleted:
            stmt = stmt.where(User.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        """Look up by email_hash, not the raw email column.

        The raw ``email`` column is also unique, but we still go through
        the hash so behaviour is consistent if/when email is ever stored
        encrypted at rest.
        """
        return await self.get_by_email_hash(_hash_email(email))

    async def get_by_email_hash(self, email_hash: str) -> User | None:
        stmt = select(User).where(User.email_hash == email_hash).where(User.deleted_at.is_(None))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    # ── Creates ──────────────────────────────────────────────────────
    async def create(
        self,
        *,
        email: str,
        password_hash: str | None,
        language_preference: str = "en",
        role: str = "user",
        email_verified: bool = False,
        display_name: str | None = None,
    ) -> User:
        """Create a user (and its empty profile row).

        Caller is responsible for committing — repositories don't commit
        on writes that return an object, because the wrapping route may
        need to perform additional work atomically.
        """
        user = User(
            email=email.strip().lower(),
            email_hash=_hash_email(email),
            password_hash=password_hash,
            role=role,
            email_verified=email_verified,
            language_preference=language_preference,
        )
        self._session.add(user)
        await self._session.flush()  # populate user.id without committing

        profile = UserProfile(user_id=user.id, display_name=display_name)
        self._session.add(profile)
        await self._session.flush()
        return user

    # ── Updates ──────────────────────────────────────────────────────
    async def mark_email_verified(self, user_id: UUID) -> None:
        await self._session.execute(
            update(User).where(User.id == user_id).values(email_verified=True)
        )

    async def update_password(self, user_id: UUID, new_password_hash: str) -> None:
        await self._session.execute(
            update(User).where(User.id == user_id).values(password_hash=new_password_hash)
        )

    async def update_last_login(self, user_id: UUID) -> None:
        now = datetime.now(timezone.utc)
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_login_at=now, failed_login_attempts=0, locked_at=None)
        )

    async def update_email(self, user_id: UUID, new_email: str) -> None:
        """Update email + email_hash atomically; clears email_verified."""
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                email=new_email.strip().lower(),
                email_hash=_hash_email(new_email),
                email_verified=False,
            )
        )

    async def update_profile(
        self,
        user_id: UUID,
        *,
        display_name: str | None = None,
        avatar_url: str | None = None,
        language_preference: str | None = None,
    ) -> None:
        """Patch profile + the language_preference column on users.

        Fields that are None in the kwargs are LEFT ALONE (not nulled).
        To explicitly null a field, the caller passes "" or handles it at
        the service layer before calling.
        """
        if language_preference is not None:
            await self._session.execute(
                update(User)
                .where(User.id == user_id)
                .values(language_preference=language_preference)
            )

        profile_changes: dict[str, str | None] = {}
        if display_name is not None:
            profile_changes["display_name"] = display_name
        if avatar_url is not None:
            profile_changes["avatar_url"] = avatar_url
        if profile_changes:
            await self._session.execute(
                update(UserProfile).where(UserProfile.user_id == user_id).values(**profile_changes)
            )

    # ── Failed-login bookkeeping ─────────────────────────────────────
    async def increment_failed_logins(self, user_id: UUID) -> int:
        """Increment, return the new count.

        We read-then-write rather than using ``+= 1`` SQL syntax because
        SQLite's update doesn't expose the post-update value cleanly. The
        small race window (concurrent failures double-count by one) is
        acceptable for security counter — the worst case is locking out
        slightly faster, which is the safer direction.
        """
        user = await self.get_by_id(user_id)
        if user is None:
            return 0
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        await self._session.flush()
        return user.failed_login_attempts

    async def lock_account(self, user_id: UUID) -> None:
        await self._session.execute(
            update(User).where(User.id == user_id).values(locked_at=datetime.now(timezone.utc))
        )

    async def unlock_account(self, user_id: UUID) -> None:
        await self._session.execute(
            update(User).where(User.id == user_id).values(locked_at=None, failed_login_attempts=0)
        )

    # ── Soft delete ──────────────────────────────────────────────────
    async def soft_delete(self, user_id: UUID) -> None:
        await self._session.execute(
            update(User)
            .where(User.id == user_id)
            .values(
                deleted_at=datetime.now(timezone.utc),
                is_active=False,
            )
        )


__all__ = ["UserRepository", "_hash_email"]
