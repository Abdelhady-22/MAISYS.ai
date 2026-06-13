"""Tests for shared.models.pagination."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.models.pagination import PaginatedResponse, PaginationParams


class TestPaginationParamsDefaults:
    def test_default_values(self) -> None:
        p = PaginationParams()
        assert p.page == 1
        assert p.page_size == 20
        assert p.order_by == "created_at"
        assert p.order_dir == "desc"


class TestPaginationParamsValidation:
    def test_page_must_be_at_least_1(self) -> None:
        with pytest.raises(ValidationError):
            PaginationParams(page=0)
        with pytest.raises(ValidationError):
            PaginationParams(page=-1)

    def test_page_size_min_1(self) -> None:
        with pytest.raises(ValidationError):
            PaginationParams(page_size=0)
        with pytest.raises(ValidationError):
            PaginationParams(page_size=-5)

    def test_page_size_max_100(self) -> None:
        with pytest.raises(ValidationError):
            PaginationParams(page_size=101)
        with pytest.raises(ValidationError):
            PaginationParams(page_size=1000)

    def test_page_size_boundaries_accepted(self) -> None:
        assert PaginationParams(page_size=1).page_size == 1
        assert PaginationParams(page_size=100).page_size == 100

    def test_order_dir_validation(self) -> None:
        assert PaginationParams(order_dir="asc").order_dir == "asc"
        assert PaginationParams(order_dir="desc").order_dir == "desc"
        with pytest.raises(ValidationError):
            PaginationParams(order_dir="invalid")  # type: ignore[arg-type]

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            PaginationParams(extra_field="nope")  # type: ignore[call-arg]


class TestOrderByValidation:
    def test_accepts_alphanumeric_and_underscore(self) -> None:
        assert PaginationParams(order_by="name").order_by == "name"
        assert PaginationParams(order_by="created_at").order_by == "created_at"
        assert PaginationParams(order_by="user_id_2").order_by == "user_id_2"
        assert PaginationParams(order_by="UPPER_CASE").order_by == "UPPER_CASE"

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValidationError):
            PaginationParams(order_by="")

    @pytest.mark.parametrize(
        "bad_value",
        [
            "name; DROP TABLE users",
            "name,id",
            "name DESC",
            "users.name",
            "name-with-dashes",
            "name with spaces",
            "name'",
            "name)",
            "(name)",
        ],
    )
    def test_rejects_injection_attempts(self, bad_value: str) -> None:
        with pytest.raises(ValidationError):
            PaginationParams(order_by=bad_value)


class TestOffsetAndLimit:
    def test_offset_first_page(self) -> None:
        p = PaginationParams(page=1, page_size=10)
        assert p.offset == 0
        assert p.limit == 10

    def test_offset_middle_page(self) -> None:
        p = PaginationParams(page=3, page_size=10)
        assert p.offset == 20
        assert p.limit == 10

    def test_offset_with_custom_page_size(self) -> None:
        p = PaginationParams(page=5, page_size=25)
        assert p.offset == 100


class TestPaginatedResponseBuild:
    def test_basic(self) -> None:
        items = [1, 2, 3]
        params = PaginationParams(page=1, page_size=10)
        resp = PaginatedResponse[int].build(items, total=3, params=params)
        assert resp.items == [1, 2, 3]
        assert resp.total == 3
        assert resp.page == 1
        assert resp.page_size == 10
        assert resp.total_pages == 1

    def test_total_pages_exact_division(self) -> None:
        params = PaginationParams(page=1, page_size=10)
        resp = PaginatedResponse[int].build([], total=30, params=params)
        assert resp.total_pages == 3

    def test_total_pages_partial_last_page(self) -> None:
        params = PaginationParams(page=1, page_size=10)
        resp = PaginatedResponse[int].build([], total=25, params=params)
        assert resp.total_pages == 3  # 10 + 10 + 5

    def test_total_pages_single_item(self) -> None:
        params = PaginationParams(page=1, page_size=10)
        resp = PaginatedResponse[int].build([1], total=1, params=params)
        assert resp.total_pages == 1

    def test_empty_results(self) -> None:
        params = PaginationParams(page=1, page_size=10)
        resp = PaginatedResponse[int].build([], total=0, params=params)
        assert resp.items == []
        assert resp.total == 0
        assert resp.total_pages == 0

    def test_negative_total_rejected(self) -> None:
        params = PaginationParams(page=1, page_size=10)
        with pytest.raises(ValueError):
            PaginatedResponse[int].build([], total=-1, params=params)


class TestPaginatedResponseSerialization:
    def test_serializable_to_json(self) -> None:
        params = PaginationParams(page=2, page_size=5)
        resp = PaginatedResponse[dict[str, int]].build(
            items=[{"id": 1}, {"id": 2}], total=12, params=params
        )
        dumped = resp.model_dump(mode="json")
        assert dumped == {
            "items": [{"id": 1}, {"id": 2}],
            "total": 12,
            "page": 2,
            "page_size": 5,
            "total_pages": 3,
        }

    def test_rejects_extra(self) -> None:
        with pytest.raises(ValidationError):
            PaginatedResponse[int](  # type: ignore[call-arg]
                items=[],
                total=0,
                page=1,
                page_size=10,
                total_pages=0,
                extra="bad",
            )
