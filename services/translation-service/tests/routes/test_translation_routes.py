"""Integration tests for /translate routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_healthz(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz_reports_available_modes(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert set(body["modes"]) == {"google", "local", "llm"}


@pytest.mark.asyncio
async def test_translate_happy_path(client: AsyncClient) -> None:
    response = await client.post(
        "/translate",
        json={
            "text": "Hello world",
            "source_lang": "en",
            "target_lang": "ar",
            "mode": "google",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["translated_text"] == "[en→ar] Hello world"
    assert data["source_lang_detected"] == "en"
    assert data["target_lang"] == "ar"
    assert data["mode_used"] == "google"
    assert data["cached"] is False


@pytest.mark.asyncio
async def test_translate_auto_detect(client: AsyncClient) -> None:
    response = await client.post(
        "/translate",
        json={
            "text": "مرحبا بك",
            "target_lang": "en",
            "mode": "google",
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source_lang_detected"] == "ar"


@pytest.mark.asyncio
async def test_translate_second_call_is_cached(client: AsyncClient) -> None:
    body = {
        "text": "Hello",
        "source_lang": "en",
        "target_lang": "ar",
        "mode": "google",
    }
    first = await client.post("/translate", json=body)
    second = await client.post("/translate", json=body)
    assert first.json()["data"]["cached"] is False
    assert second.json()["data"]["cached"] is True


@pytest.mark.asyncio
async def test_translate_invalid_target_lang_422(client: AsyncClient) -> None:
    response = await client.post(
        "/translate",
        json={
            "text": "Hello",
            "source_lang": "en",
            "target_lang": "fr",  # not allowed
            "mode": "google",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_translate_extra_field_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/translate",
        json={
            "text": "Hello",
            "source_lang": "en",
            "target_lang": "ar",
            "mode": "google",
            "unexpected": "field",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_translate_empty_text_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/translate",
        json={
            "text": "",
            "source_lang": "en",
            "target_lang": "ar",
            "mode": "google",
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_translate_batch_happy_path(client: AsyncClient) -> None:
    response = await client.post(
        "/translate/batch",
        json={
            "items": [
                {
                    "text": "Hello",
                    "source_lang": "en",
                    "target_lang": "ar",
                    "mode": "google",
                },
                {
                    "text": "World",
                    "source_lang": "en",
                    "target_lang": "ar",
                    "mode": "llm",
                },
            ]
        },
    )
    assert response.status_code == 200
    items = response.json()["data"]["items"]
    assert len(items) == 2
    assert items[0]["translated_text"] == "[en→ar] Hello"
    assert items[1]["translated_text"] == "[en→ar] World"
    assert items[0]["mode_used"] == "google"
    assert items[1]["mode_used"] == "llm"


@pytest.mark.asyncio
async def test_translate_batch_empty_items_rejected(client: AsyncClient) -> None:
    response = await client.post("/translate/batch", json={"items": []})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_translate_batch_over_50_items_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/translate/batch",
        json={
            "items": [
                {
                    "text": f"item-{i}",
                    "source_lang": "en",
                    "target_lang": "ar",
                    "mode": "google",
                }
                for i in range(51)
            ]
        },
    )
    assert response.status_code == 422
