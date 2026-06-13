"""MAISYS shared auth module — JWT validation, FastAPI deps, and RBAC.

Every MAISYS service except auth-service uses this module to validate
incoming bearer tokens. auth-service issues the tokens; everyone else
validates them with the same JWT_SECRET via decode_token.

Typical service-side usage in a route:

    from fastapi import Depends
    from shared.auth import (
        TokenPayload, get_current_user, require_role, Role,
    )

    @router.get("/me")
    async def me(user: TokenPayload = Depends(get_current_user)) -> dict:
        return {"id": user.sub, "role": user.role}

    @router.delete(
        "/users/{user_id}",
        dependencies=[Depends(require_role(Role.ADMIN, Role.SUPER_ADMIN))],
    )
    async def delete_user(user_id: str) -> None:
        ...
"""

from shared.auth.dependencies import get_current_user, get_current_user_optional
from shared.auth.jwt_validator import decode_token
from shared.auth.rbac import require_role
from shared.auth.types import Role, TokenPayload

__all__ = [
    "Role",
    "TokenPayload",
    "decode_token",
    "get_current_user",
    "get_current_user_optional",
    "require_role",
]
