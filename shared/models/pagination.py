"""Pagination types used by every list-style MAISYS endpoint."""

from __future__ import annotations

from math import ceil
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Query parameters for paginated list endpoints.

    Validated as Pydantic so callers can use it as a FastAPI dependency:

        @router.get("/users")
        async def list_users(params: PaginationParams = Depends()):
            ...

    `order_by` is restricted to alphanumeric/underscore characters to prevent
    naive SQL string concatenation injection. Repositories should still
    validate against an allowlist of known sortable columns.
    """

    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    order_by: str = Field(default="created_at")
    order_dir: Literal["asc", "desc"] = "desc"

    @field_validator("order_by")
    @classmethod
    def _validate_order_by(cls, v: str) -> str:
        """Allow only [A-Za-z0-9_] in order_by to defang naive SQL composition."""
        if not v:
            raise ValueError("order_by must not be empty")
        if not v.replace("_", "").isalnum():
            raise ValueError(f"order_by must be alphanumeric or underscore: got {v!r}")
        return v

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated response wrapper.

    Use the `build` classmethod rather than constructing manually so
    `total_pages` is computed consistently.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[T]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_pages: int = Field(ge=0)

    @classmethod
    def build(
        cls,
        items: list[T],
        total: int,
        params: PaginationParams,
    ) -> PaginatedResponse[T]:
        """Construct a PaginatedResponse with total_pages computed from inputs."""
        if total < 0:
            raise ValueError(f"total must be non-negative: got {total}")
        total_pages = ceil(total / params.page_size) if total > 0 else 0
        return cls(
            items=items,
            total=total,
            page=params.page,
            page_size=params.page_size,
            total_pages=total_pages,
        )
