"""Tests for the EndlessMedical scraper (no network, no live bucket)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scrapers import endlessmedical_scraper as em

OUTPUT = "gs://maisys-data-dev"


# ── Fake GCS ───────────────────────────────────────────────────────────────
class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str) -> None:
        self._bucket = bucket
        self.name = name

    def exists(self) -> bool:
        return self.name in self._bucket.store

    def upload_from_string(self, data: Any, content_type: str | None = None) -> None:
        self._bucket.store[self.name] = data.encode("utf-8") if isinstance(data, str) else data

    def download_as_text(self) -> str:
        return self._bucket.store[self.name].decode("utf-8")


class FakeBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self.store: dict[str, bytes] = {}

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


class FakeClient:
    def __init__(self) -> None:
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name: str) -> FakeBucket:
        return self.buckets.setdefault(name, FakeBucket(name))


# ── Fake HTTP session ─────────────────────────────────────────────────────
class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _handle(url: str) -> Any:
    if url.endswith("/GetFeatures"):
        return {"data": ["Fever", "Cough"]}
    if url.endswith("/GetOutcomes"):
        return {"data": ["Influenza"]}
    if url.endswith("/InitSession"):
        return {"SessionID": "sid-1"}
    if url.endswith("/AcceptTermsOfUse"):
        return {"status": "ok"}
    if url.endswith("/UpdateFeature"):
        return {"status": "ok"}
    if "GetSuggestedFeatures_PatientProvided" in url:
        return {"SuggestedFeatures": ["Cough"]}
    if "GetSuggestedFeatures_PhysicianProvided" in url:
        return {"SuggestedFeatures": []}
    if url.endswith("/GetSuggestedTests"):
        return {"Tests": ["CBC"]}
    if url.endswith("/Analyze"):
        return {"Diseases": [{"Influenza": 0.61}], "VariableImportances": []}
    return {"status": "ok"}


class FakeSession:
    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()

    def request(
        self, method: str, url: str, params: Any = None, headers: Any = None, timeout: Any = None
    ) -> FakeResponse:
        if any(f in url for f in self.fail):
            raise RuntimeError("boom")
        return FakeResponse(_handle(url))


def make(client: FakeClient, **kw: Any) -> em.EndlessMedicalScraper:
    kw.setdefault("session", FakeSession())
    return em.EndlessMedicalScraper(
        em.GcsSink(client, OUTPUT), sleep=lambda _: None, max_turns=2, **kw
    )


def test_full_run_writes_outputs_and_manifest() -> None:
    client = FakeClient()
    manifest = make(client, max_seed_features=1).run()
    store = client.bucket("maisys-data-dev").store
    for name in ["features", "outcomes", "feature_sessions", "multi_feature_sessions"]:
        assert f"raw/endlessmedical/{name}.json" in store
    assert "manifests/endlessmedical.json" in store
    assert manifest.failed_count == 0

    sessions = json.loads(store["raw/endlessmedical/feature_sessions.json"].decode())
    assert sessions[0]["seed_feature"] == "Fever"
    assert sessions[0]["conversation"][0]["analysis"]["top_diseases"][0]["disease"] == "Influenza"


def test_skip_if_static_exists() -> None:
    client = FakeClient()
    store = client.bucket("maisys-data-dev").store
    store["raw/endlessmedical/features.json"] = json.dumps({"features": ["Fever"]}).encode()
    make(client, max_seed_features=1).run()
    # features.json reused, not overwritten with count key.
    assert "count" not in json.loads(store["raw/endlessmedical/features.json"].decode())


def test_dry_run_writes_nothing() -> None:
    client = FakeClient()
    make(client, max_seed_features=1, dry_run=True).run()
    assert client.bucket("maisys-data-dev").store == {}


def test_optional_api_key_passed_as_header() -> None:
    client = FakeClient()
    captured: dict[str, Any] = {}

    class CapturingSession(FakeSession):
        def request(
            self,
            method: str,
            url: str,
            params: Any = None,
            headers: Any = None,
            timeout: Any = None,
        ) -> FakeResponse:
            captured["headers"] = headers
            return super().request(method, url, params, headers, timeout)

    make(client, session=CapturingSession(), api_key="k", max_seed_features=1).run()
    assert captured["headers"] == {"X-Api-Key": "k"}


def test_parse_disease_formats() -> None:
    assert em._parse_disease({"Flu": 0.5}) == {"disease": "Flu", "probability": 0.5}
    assert em._parse_disease({"name": "Flu", "probability": 0.7})["probability"] == 0.7
    assert em._parse_disease("bad") is None


# ── CLI ──────────────────────────────────────────────────────────────────────
def test_main_dry_run_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    # Optional secret absent -> still proceeds (public API).
    monkeypatch.setattr(em, "resolve_secret", lambda *a, **k: None)
    rc = em.main(["--output-bucket", OUTPUT, "--dry-run"], client=FakeClient())
    assert rc == 0


def test_main_bad_uri() -> None:
    assert em.main(["--output-bucket", "/local"], client=FakeClient()) == 2
