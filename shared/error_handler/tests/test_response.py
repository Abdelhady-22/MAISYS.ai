"""Tests for shared.error_handler.response."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.error_handler.exceptions import (
    NotFoundException,
    ValidationException,
)
from shared.error_handler.response import APIResponse, ErrorDetail


class TestErrorDetail:
    def test_basic_construction(self) -> None:
        err = ErrorDetail(code="X", message="msg")
        assert err.code == "X"
        assert err.message == "msg"
        assert err.details == {}
        assert err.correlation_id is None

    def test_with_full_payload(self) -> None:
        err = ErrorDetail(
            code="X",
            message="msg",
            details={"field": "email"},
            correlation_id="abc",
        )
        assert err.details == {"field": "email"}
        assert err.correlation_id == "abc"

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ErrorDetail(code="X", message="m", unexpected="nope")  # type: ignore[call-arg]


class TestAPIResponseOk:
    def test_with_dict_data(self) -> None:
        resp = APIResponse.ok({"key": "value"})
        assert resp.success is True
        assert resp.data == {"key": "value"}
        assert resp.error is None
        assert resp.metadata == {}

    def test_with_metadata(self) -> None:
        resp = APIResponse.ok({"key": "value"}, metadata={"count": 1})
        assert resp.metadata == {"count": 1}

    def test_with_list_data(self) -> None:
        resp = APIResponse.ok([1, 2, 3])
        assert resp.success is True
        assert resp.data == [1, 2, 3]

    def test_with_none_data_is_allowed(self) -> None:
        # APIResponse[None] is valid (e.g. for 204-style returns)
        resp: APIResponse[None] = APIResponse.ok(None)
        assert resp.success is True
        assert resp.data is None


class TestAPIResponseErrorFromException:
    def test_from_not_found(self) -> None:
        exc = NotFoundException("Resource not found", details={"id": 42})
        resp = APIResponse.error_from_exception(exc)
        assert resp.success is False
        assert resp.data is None
        assert resp.error is not None
        assert resp.error.code == "NOT_FOUND"
        assert resp.error.message == "Resource not found"
        assert resp.error.details == {"id": 42}

    def test_correlation_id_propagated(self) -> None:
        exc = ValidationException("bad input", correlation_id="req-xyz")
        resp = APIResponse.error_from_exception(exc)
        assert resp.error is not None
        assert resp.error.correlation_id == "req-xyz"

    def test_correlation_id_none_when_unset(self) -> None:
        exc = ValidationException("bad")
        resp = APIResponse.error_from_exception(exc)
        assert resp.error is not None
        assert resp.error.correlation_id is None

    def test_json_serializable(self) -> None:
        exc = ValidationException("bad", details={"field": "email"})
        resp = APIResponse.error_from_exception(exc)
        dumped = resp.model_dump(mode="json")
        assert dumped["success"] is False
        assert dumped["data"] is None
        assert dumped["error"]["code"] == "VALIDATION_FAILED"
        assert dumped["error"]["details"] == {"field": "email"}


class TestAPIResponseEnvelopeShape:
    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            APIResponse(  # type: ignore[call-arg]
                success=True, data={"x": 1}, error=None, metadata={}, extra="bad"
            )
