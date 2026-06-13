"""Tests for the Infermedica scraper (no network, no live bucket)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from scrapers import infermedica_scraper as inf

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


# ── Fake HTTP ───────────────────────────────────────────────────────────────
class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _handle(url: str) -> Any:
    if url.endswith("/info"):
        return {"symptoms_count": 1}
    if "/symptoms/" in url:
        return {"id": "s1", "name": "Fever", "detail": True}
    if url.endswith("/symptoms"):
        return [{"id": "s1", "name": "Fever"}]
    if "/conditions/" in url:
        return {"id": "c1", "detail": True}
    if url.endswith("/conditions"):
        return [{"id": "c1", "name": "Flu"}]
    if "/risk_factors/" in url:
        return {"id": "r1", "detail": True}
    if url.endswith("/risk_factors"):
        return [{"id": "r1", "name": "Smoking"}]
    if url.endswith("/parse"):
        return {"mentions": []}
    if "/search" in url:
        return [{"id": "s1"}]
    if url.endswith("/diagnosis"):
        return {
            "question": None,
            "conditions": [{"id": "c1", "name": "Flu", "probability": 0.5}],
            "should_stop": True,
        }
    if url.endswith("/triage"):
        return {"triage_level": "consultation"}
    if url.endswith("/explain"):
        return {"supporting_evidence": []}
    if url.endswith("/specialist"):
        return {"recommended_channel": "x"}
    return {}


class FakeHttp:
    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()

    def get(
        self, url: str, headers: Any = None, params: Any = None, timeout: Any = None
    ) -> FakeResponse:
        if any(f in url for f in self.fail):
            raise RuntimeError("boom")
        return FakeResponse(_handle(url))

    def post(
        self, url: str, headers: Any = None, json: Any = None, timeout: Any = None
    ) -> FakeResponse:
        if any(f in url for f in self.fail):
            raise RuntimeError("boom")
        return FakeResponse(_handle(url))


def make(client: FakeClient, **kw: Any) -> inf.InfermedicaScraper:
    kw.setdefault("http", FakeHttp())
    return inf.InfermedicaScraper(
        inf.GcsSink(client, OUTPUT), app_id="id", app_key="key", sleep=lambda _: None, **kw
    )


def test_full_run_writes_outputs_and_manifest() -> None:
    client = FakeClient()
    manifest = make(client, max_seed_symptoms=1).run()
    store = client.bucket("maisys-data-dev").store
    for name in [
        "info",
        "symptoms",
        "conditions",
        "risk_factors",
        "parse_samples",
        "search_samples",
        "diagnosis_flows",
    ]:
        assert f"raw/infermedica/{name}.json" in store
    assert "manifests/infermedica.json" in store
    assert manifest.failed_count == 0
    flows = json.loads(store["raw/infermedica/diagnosis_flows.json"].decode())
    assert len(flows) == 6  # 1 seed x 2 sexes x 3 ages
    assert flows[0]["triage"]["triage_level"] == "consultation"


def test_skip_if_static_exists() -> None:
    client = FakeClient()
    client.bucket("maisys-data-dev").store["raw/infermedica/info.json"] = b'{"old": true}'
    make(client, max_seed_symptoms=1).run()
    # info.json not overwritten (skipped).
    assert json.loads(
        client.bucket("maisys-data-dev").store["raw/infermedica/info.json"].decode()
    ) == {"old": True}


def test_force_overwrites() -> None:
    client = FakeClient()
    client.bucket("maisys-data-dev").store["raw/infermedica/info.json"] = b'{"old": true}'
    make(client, max_seed_symptoms=1, force=True).run()
    assert "symptoms_count" in json.loads(
        client.bucket("maisys-data-dev").store["raw/infermedica/info.json"].decode()
    )


def test_dry_run_writes_nothing() -> None:
    client = FakeClient()
    make(client, max_seed_symptoms=1, dry_run=True).run()
    assert client.bucket("maisys-data-dev").store == {}


def test_api_error_recorded() -> None:
    client = FakeClient()
    manifest = make(client, max_seed_symptoms=1, http=FakeHttp(fail={"/info"})).run()
    assert manifest.failed_count >= 1


# ── CLI ──────────────────────────────────────────────────────────────────────
def test_main_bad_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inf, "resolve_secret", lambda *a, **k: "x")
    assert inf.main(["--output-bucket", "/local"], client=FakeClient()) == 2


def test_main_missing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*a: Any, **k: Any) -> str:
        raise inf.SecretError("missing")

    monkeypatch.setattr(inf, "resolve_secret", _raise)
    assert inf.main(["--output-bucket", OUTPUT], client=FakeClient()) == 2


def test_main_dry_run_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(inf, "resolve_secret", lambda *a, **k: "x")
    rc = inf.main(["--output-bucket", OUTPUT, "--dry-run"], client=FakeClient())
    assert rc == 0
