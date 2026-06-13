"""Role-based access control for MAISYS routes.

`require_role(*roles)` returns a FastAPI dependency that:
1. Resolves the current user via `get_current_user`
2. Checks the user's role is in the allowlist
3. Raises AuthorizationException if not
4. Returns the TokenPayload on success (so endpoints that need the user
   can list the dependency in their signature)

Usage:

    from fastapi import Depends
    from shared.auth import require_role, Role

    # As a route dependency without using the payload
    @router.delete(
        "/users/{user_id}",
        dependencies=[Depends(require_role(Role.ADMIN, Role.SUPER_ADMIN))],
    )
    async def delete_user(user_id: str) -> None: ...

    # As a signature dependency to receive the payload
    @router.get("/admin/overview")
    async def admin_overview(
        user: TokenPayload = Depends(require_role(Role.ADMIN)),
    ) -> dict: ...
"""

from __future__ import annotations

from typing import Callable, Coroutine

from fastapi import Depends

from shared.auth.dependencies import get_current_user
from shared.auth.types import Role, TokenPayload
from shared.error_handler import AuthorizationException


def require_role(
    *allowed: Role,
) -> Callable[[TokenPayload], Coroutine[None, None, TokenPayload]]:
    """Build a FastAPI dependency that enforces role membership.

    Args:
        *allowed: one or more Role values that may access the route.

    Returns:
        An async function suitable for `Depends(...)`. It returns the
        TokenPayload on success.
    """
    if not allowed:
        raise ValueError("require_role must be called with at least one Role argument")

    async def _checker(
        current_user: TokenPayload = Depends(get_current_user),
    ) -> TokenPayload:
        if current_user.role not in allowed:
            raise AuthorizationException(
                "User role does not have access to this resource",
                code="ROLE_NOT_ALLOWED",
                details={
                    "required": sorted(r.value for r in allowed),
                    "actual": current_user.role.value,
                },
            )
        return current_user

    return _checker
