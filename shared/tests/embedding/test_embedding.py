"""Tests for shared.embedding."""

from __future__ import annotations

import pytest

from shared.embedding import (
    BilingualEmbedder,
    EmbeddedItem,
    FakeEmbedder,
    detect_language,
)

# ─── FakeEmbedder ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_embedder_returns_correct_dimension() -> None:
    fake = FakeEmbedder(dimension=64)
    vectors = await fake.embed(["hello", "world"])
    assert len(vectors) == 2
    assert all(len(v) == 64 for v in vectors)


@pytest.mark.asyncio
async def test_fake_embedder_is_deterministic() -> None:
    fake = FakeEmbedder(dimension=32)
    a = await fake.embed(["paracetamol"])
    b = await fake.embed(["paracetamol"])
    assert a == b


@pytest.mark.asyncio
async def test_fake_embedder_distinct_inputs_distinct_vectors() -> None:
    fake = FakeEmbedder(dimension=32)
    [a] = await fake.embed(["aspirin"])
    [b] = await fake.embed(["ibuprofen"])
    assert a != b


@pytest.mark.asyncio
async def test_fake_embedder_empty_input() -> None:
    fake = FakeEmbedder()
    assert await fake.embed([]) == []


def test_fake_embedder_rejects_zero_dimension() -> None:
    with pytest.raises(ValueError):
        FakeEmbedder(dimension=0)


# ─── detect_language ──────────────────────────────────────────────


def test_detect_language_english_text() -> None:
    assert detect_language("The patient was prescribed ibuprofen for headache.") == "en"


def test_detect_language_arabic_text() -> None:
    assert detect_language("تم وصف الإيبوبروفين للمريض لعلاج الصداع") == "ar"


def test_detect_language_mostly_arabic_with_english_words() -> None:
    """Mixed text with majority Arabic script should detect as ar."""
    text = "المريض patient الإيبوبروفين"
    assert detect_language(text) == "ar"


def test_detect_language_empty_text_defaults_to_en() -> None:
    assert detect_language("") == "en"


# ─── BilingualEmbedder ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bilingual_routes_english_to_en_embedder() -> None:
    en = FakeEmbedder(dimension=8, model_name="fake-en")
    ar = FakeEmbedder(dimension=16, model_name="fake-ar")
    bi = BilingualEmbedder(en_embedder=en, ar_embedder=ar)

    result = await bi.embed(["The drug treats hypertension."])
    assert len(result) == 1
    assert result[0].language == "en"
    assert result[0].model_name == "fake-en"
    assert len(result[0].vector) == 8


@pytest.mark.asyncio
async def test_bilingual_routes_arabic_to_ar_embedder() -> None:
    en = FakeEmbedder(dimension=8, model_name="fake-en")
    ar = FakeEmbedder(dimension=16, model_name="fake-ar")
    bi = BilingualEmbedder(en_embedder=en, ar_embedder=ar)

    result = await bi.embed(["الإيبوبروفين علاج فعال للألم"])
    assert len(result) == 1
    assert result[0].language == "ar"
    assert result[0].model_name == "fake-ar"
    assert len(result[0].vector) == 16


@pytest.mark.asyncio
async def test_bilingual_preserves_input_order() -> None:
    en = FakeEmbedder(dimension=8, model_name="fake-en")
    ar = FakeEmbedder(dimension=16, model_name="fake-ar")
    bi = BilingualEmbedder(en_embedder=en, ar_embedder=ar)
    texts = [
        "English sentence one",
        "الجملة العربية الأولى",
        "English sentence two",
        "الجملة العربية الثانية",
    ]
    result = await bi.embed(texts)
    assert len(result) == 4
    # Each EmbeddedItem.original_index matches its position in input
    for i, item in enumerate(result):
        assert item.original_index == i
        assert item.text == texts[i]


@pytest.mark.asyncio
async def test_bilingual_empty_input() -> None:
    en = FakeEmbedder(model_name="fake-en")
    ar = FakeEmbedder(model_name="fake-ar")
    bi = BilingualEmbedder(en_embedder=en, ar_embedder=ar)
    assert await bi.embed([]) == []


@pytest.mark.asyncio
async def test_bilingual_returns_embeddeditem_instances() -> None:
    en = FakeEmbedder(model_name="fake-en")
    ar = FakeEmbedder(model_name="fake-ar")
    bi = BilingualEmbedder(en_embedder=en, ar_embedder=ar)
    result = await bi.embed(["Hello"])
    assert isinstance(result[0], EmbeddedItem)


def test_bilingual_exposes_per_language_dimensions() -> None:
    en = FakeEmbedder(dimension=1536, model_name="fake-en")
    ar = FakeEmbedder(dimension=384, model_name="fake-ar")
    bi = BilingualEmbedder(en_embedder=en, ar_embedder=ar)
    assert bi.en_dimension == 1536
    assert bi.ar_dimension == 384
