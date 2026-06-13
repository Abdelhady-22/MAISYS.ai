"""Tests for shared.models.types."""

from __future__ import annotations

from decimal import Decimal
from typing import get_args

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from shared.models.types import (
    BilingualText,
    ISOCountryCode,
    ISOLanguageCode,
    Money,
    PercentFloat,
    PositiveFloat,
)


class TestISOLanguageCode:
    def test_valid_literal_values(self) -> None:
        assert "ar" in get_args(ISOLanguageCode)
        assert "en" in get_args(ISOLanguageCode)
        assert len(get_args(ISOLanguageCode)) == 2

    def test_pydantic_accepts_valid(self) -> None:
        class M(BaseModel):
            lang: ISOLanguageCode

        assert M(lang="ar").lang == "ar"
        assert M(lang="en").lang == "en"

    def test_pydantic_rejects_invalid(self) -> None:
        class M(BaseModel):
            lang: ISOLanguageCode

        with pytest.raises(ValidationError):
            M(lang="fr")  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            M(lang="AR")  # type: ignore[arg-type]


class TestISOCountryCode:
    def test_includes_mena(self) -> None:
        codes = get_args(ISOCountryCode)
        for c in ("EG", "SA", "AE", "JO", "MA", "TN"):
            assert c in codes

    def test_includes_english_speaking(self) -> None:
        codes = get_args(ISOCountryCode)
        for c in ("US", "GB", "CA", "AU"):
            assert c in codes

    def test_pydantic_rejects_unknown(self) -> None:
        class M(BaseModel):
            country: ISOCountryCode

        with pytest.raises(ValidationError):
            M(country="ZZ")  # type: ignore[arg-type]


class TestBilingualText:
    def test_typed_dict_shape(self) -> None:
        bt: BilingualText = {"ar": "مرحبا", "en": "Hello"}
        assert bt["ar"] == "مرحبا"
        assert bt["en"] == "Hello"

    def test_pydantic_accepts_complete(self) -> None:
        class M(BaseModel):
            label: BilingualText

        m = M(label={"ar": "اختبار", "en": "test"})
        assert m.label["ar"] == "اختبار"
        assert m.label["en"] == "test"

    def test_pydantic_rejects_missing_language(self) -> None:
        class M(BaseModel):
            label: BilingualText

        with pytest.raises(ValidationError):
            M(label={"ar": "اختبار"})  # type: ignore[typeddict-item]
        with pytest.raises(ValidationError):
            M(label={"en": "only english"})  # type: ignore[typeddict-item]


class _PercentModel(BaseModel):
    p: PercentFloat


class _PositiveModel(BaseModel):
    x: PositiveFloat


class TestPercentFloat:
    def test_in_range(self) -> None:
        assert _PercentModel(p=0.0).p == 0.0
        assert _PercentModel(p=0.5).p == 0.5
        assert _PercentModel(p=1.0).p == 1.0

    def test_below_range(self) -> None:
        with pytest.raises(ValidationError):
            _PercentModel(p=-0.1)

    def test_above_range(self) -> None:
        with pytest.raises(ValidationError):
            _PercentModel(p=1.01)
        with pytest.raises(ValidationError):
            _PercentModel(p=100.0)


class TestPositiveFloat:
    def test_positive_accepted(self) -> None:
        assert _PositiveModel(x=0.001).x == 0.001
        assert _PositiveModel(x=1000.0).x == 1000.0

    def test_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _PositiveModel(x=0.0)

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _PositiveModel(x=-1.0)


class TestMoney:
    def test_typed_dict_shape(self) -> None:
        m: Money = {"amount": Decimal("19.99"), "currency": "USD"}
        assert m["amount"] == Decimal("19.99")
        assert m["currency"] == "USD"

    def test_pydantic_accepts_with_decimal(self) -> None:
        class M(BaseModel):
            model_config = ConfigDict(arbitrary_types_allowed=True)
            price: Money

        m = M(price={"amount": Decimal("10.50"), "currency": "EGP"})
        assert m.price["amount"] == Decimal("10.50")
        assert m.price["currency"] == "EGP"
