"""Tests for shared.error_handler.exceptions."""

from __future__ import annotations

import pytest

from shared.error_handler.exceptions import (
    AuthenticationException,
    AuthorizationException,
    ConflictException,
    ExternalServiceException,
    MaisysException,
    MedicalSafetyException,
    NotFoundException,
    RateLimitException,
    ValidationException,
)


class TestMaisysExceptionBase:
    def test_default_attributes(self) -> None:
        exc = MaisysException()
        assert exc.message == "An internal error occurred"
        assert exc.code == "INTERNAL_ERROR"
        assert exc.status_code == 500
        assert exc.details == {}
        assert exc.correlation_id is None
        assert exc.cause is None

    def test_custom_message(self) -> None:
        exc = MaisysException("Something broke")
        assert exc.message == "Something broke"
        assert str(exc) == "Something broke"

    def test_all_custom_attributes(self) -> None:
        cause = ValueError("underlying")
        exc = MaisysException(
            "Custom",
            code="CUSTOM",
            status_code=418,
            details={"key": "value"},
            correlation_id="req-123",
            cause=cause,
        )
        assert exc.code == "CUSTOM"
        assert exc.status_code == 418
        assert exc.details == {"key": "value"}
        assert exc.correlation_id == "req-123"
        assert exc.cause is cause

    def test_is_raisable(self) -> None:
        with pytest.raises(MaisysException) as exc_info:
            raise MaisysException("test")
        assert exc_info.value.message == "test"

    def test_details_default_to_empty_dict_not_shared(self) -> None:
        # Guard against the classic mutable-default bug
        a = MaisysException("a")
        b = MaisysException("b")
        a.details["x"] = 1
        assert b.details == {}


class TestSubclassDefaults:
    @pytest.mark.parametrize(
        ("exc_cls", "expected_code", "expected_status"),
        [
            (ValidationException, "VALIDATION_FAILED", 400),
            (AuthenticationException, "AUTHENTICATION_FAILED", 401),
            (AuthorizationException, "AUTHORIZATION_FAILED", 403),
            (NotFoundException, "NOT_FOUND", 404),
            (ConflictException, "CONFLICT", 409),
            (RateLimitException, "RATE_LIMITED", 429),
            (ExternalServiceException, "EXTERNAL_SERVICE_ERROR", 502),
            (MedicalSafetyException, "MEDICAL_SAFETY_BLOCKED", 451),
        ],
    )
    def test_default_code_and_status(
        self,
        exc_cls: type[MaisysException],
        expected_code: str,
        expected_status: int,
    ) -> None:
        exc = exc_cls("test message")
        assert exc.code == expected_code
        assert exc.status_code == expected_status
        assert exc.message == "test message"

    def test_subclass_code_overridable(self) -> None:
        exc = ValidationException(
            "bad email",
            code="EMAIL_INVALID",
            details={"field": "email"},
        )
        assert exc.code == "EMAIL_INVALID"
        assert exc.status_code == 400  # default status preserved
        assert exc.details == {"field": "email"}

    def test_subclass_status_code_overridable(self) -> None:
        # Rare but supported — for codes that don't fit cleanly
        exc = ExternalServiceException("upstream timeout", status_code=504)
        assert exc.status_code == 504

    def test_subclass_is_maisys_exception(self) -> None:
        with pytest.raises(MaisysException):
            raise NotFoundException("missing")

    def test_class_attribute_not_clobbered_by_instance(self) -> None:
        # Setting on one instance should not change the class default
        e1 = ValidationException("a", code="X")
        e2 = ValidationException("b")
        assert e1.code == "X"
        assert e2.code == "VALIDATION_FAILED"
        assert ValidationException.code == "VALIDATION_FAILED"
