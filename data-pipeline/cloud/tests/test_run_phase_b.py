"""Tests for the Phase B orchestrator.

No GCS, no real subprocesses, no Secret Manager: an in-memory GCS fake stands in
for ``google.cloud.storage`` and the subprocess runner + prerequisite checkers
are injected — per the data-pipeline rule that tests must not depend on a live
external service.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from cloud import run_phase_b as pb

OUTPUT = "gs://maisys-data-dev"


# ──────────────────────────────────────────────────────────────────────────
# In-memory GCS fake
# ──────────────────────────────────────────────────────────────────────────
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
    def __init__(self, name: str, *, accessible: bool = True) -> None:
        self.name = name
        self.store: dict[str, bytes] = {}
        self._accessible = accessible

    def exists(self) -> bool:
        return self._accessible

    def blob(self, name: str) -> FakeBlob:
        return FakeBlob(self, name)


class FakeClient:
    def __init__(self, *, accessible: bool = True) -> None:
        self._accessible = accessible
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name: str) -> FakeBucket:
        return self.buckets.setdefault(name, FakeBucket(name, accessible=self._accessible))


# ──────────────────────────────────────────────────────────────────────────
# Fake subprocess runner
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class FakeProc:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def make_runner(
    *,
    fail_scripts: set[str] | None = None,
    calls: list[list[str]] | None = None,
) -> pb.Runner:
    """Runner that fails commands whose script path contains any ``fail_scripts``."""
    fails = fail_scripts or set()

    def _runner(cmd: list[str]) -> pb.RunResult:
        if calls is not None:
            calls.append(cmd)
        script = cmd[1] if len(cmd) > 1 else ""
        if any(token in script for token in fails):
            return FakeProc(returncode=1, stderr=f"boom in {script}")
        return FakeProc(returncode=0, stdout="ok")

    return _runner


def make_orchestrator(client: FakeClient, **kwargs: Any) -> pb.PhaseBOrchestrator:
    kwargs.setdefault("runner", make_runner())
    kwargs.setdefault("bucket_checker", lambda: True)
    kwargs.setdefault("secret_checker", lambda name: True)
    return pb.PhaseBOrchestrator(client, OUTPUT, **kwargs)


# ──────────────────────────────────────────────────────────────────────────
# Selection / registry
# ──────────────────────────────────────────────────────────────────────────
def test_registry_counts() -> None:
    assert len(pb.SCRAPER_SOURCES) == 11  # Mayo 4 + MedlinePlus 5 + infermedica + endless
    assert len(pb.DOWNLOADER_SOURCES) == 4
    assert len(pb.ALL_SOURCES) == 15


def test_resolve_selection_skips() -> None:
    assert all(s.kind == "downloader" for s in pb.resolve_selection(None, True, False))
    assert all(s.kind == "scraper" for s in pb.resolve_selection(None, False, True))


def test_resolve_selection_only() -> None:
    chosen = pb.resolve_selection(["mayo_diseases", "huggingface"], False, False)
    assert {s.name for s in chosen} == {"mayo_diseases", "huggingface"}


def test_resolve_selection_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown source"):
        pb.resolve_selection(["not_a_source"], False, False)


def test_command_uses_output_subpath() -> None:
    client = FakeClient()
    orch = make_orchestrator(client)
    hf = next(s for s in pb.ALL_SOURCES if s.name == "huggingface")
    cmd = orch.command_for(hf)
    assert cmd[1].endswith("download_huggingface_medical.py")
    assert cmd[-1] == "gs://maisys-data-dev/beta_training/raw_downloads/huggingface"


# ──────────────────────────────────────────────────────────────────────────
# Prerequisites
# ──────────────────────────────────────────────────────────────────────────
def test_prereq_bucket_inaccessible_raises() -> None:
    client = FakeClient()
    orch = make_orchestrator(client, bucket_checker=lambda: False)
    with pytest.raises(pb.PrerequisiteError, match="not accessible"):
        orch.run()


def test_prereq_missing_secret_raises() -> None:
    client = FakeClient()
    orch = make_orchestrator(client, secret_checker=lambda name: name != "kaggle-api-key")
    with pytest.raises(pb.PrerequisiteError, match="kaggle-api-key"):
        orch.run()


# ──────────────────────────────────────────────────────────────────────────
# Full run
# ──────────────────────────────────────────────────────────────────────────
def test_full_run_all_succeed() -> None:
    client = FakeClient()
    calls: list[list[str]] = []
    orch = make_orchestrator(client, runner=make_runner(calls=calls))
    manifest = orch.run()

    assert manifest.totals["completed"] == 15
    assert manifest.totals["failed"] == 0
    assert len(calls) == 15  # every source invoked exactly once

    store = client.bucket("maisys-data-dev").store
    assert "manifests/phase_b_manifest.json" in store
    # A run log was written under logs/.
    assert any(name.startswith("logs/phase_b_") for name in store)

    written = json.loads(store["manifests/phase_b_manifest.json"].decode())
    assert len(written["sources"]) == 15
    # Registry order preserved: scrapers first, downloaders last.
    assert written["sources"][0]["kind"] == "scraper"
    assert written["sources"][-1]["name"] == "knowledge_graphs"


def test_partial_failure_isolated() -> None:
    client = FakeClient()
    # One scraper and one downloader fail; everything else proceeds.
    runner = make_runner(fail_scripts={"symptoms.py", "download_chatdoctor.py"})
    orch = make_orchestrator(client, runner=runner)
    manifest = orch.run()

    statuses = {s.name: s.status for s in manifest.sources}
    assert statuses["mayo_symptoms"] == "failed"
    assert statuses["chatdoctor"] == "failed"
    assert statuses["mayo_diseases"] == "completed"
    assert statuses["huggingface"] == "completed"
    assert manifest.totals["failed"] == 2
    assert manifest.totals["completed"] == 13

    failed = next(s for s in manifest.sources if s.name == "mayo_symptoms")
    assert failed.return_code == 1
    assert failed.error is not None


# ──────────────────────────────────────────────────────────────────────────
# Resume
# ──────────────────────────────────────────────────────────────────────────
def test_resume_skips_completed_sources() -> None:
    client = FakeClient()

    # First run: chatdoctor fails, everything else completes.
    first = make_orchestrator(client, runner=make_runner(fail_scripts={"download_chatdoctor.py"}))
    first.run()

    # Second run: a runner that records calls; completed sources must be skipped,
    # only the previously-failed chatdoctor should actually run.
    calls: list[list[str]] = []
    second = make_orchestrator(client, runner=make_runner(calls=calls))
    manifest = second.run()

    ran_scripts = {cmd[1] for cmd in calls}
    assert any("download_chatdoctor.py" in s for s in ran_scripts)
    assert not any("download_huggingface_medical.py" in s for s in ran_scripts)
    assert len(calls) == 1  # only the one previously-failed source re-ran

    statuses = {s.name: s.status for s in manifest.sources}
    assert statuses["chatdoctor"] == "completed"  # now fixed
    assert statuses["huggingface"] == "skipped"  # resume-skipped
    assert manifest.totals["failed"] == 0


def test_only_forces_rerun_of_completed() -> None:
    client = FakeClient()
    make_orchestrator(client).run()  # everything completes

    calls: list[list[str]] = []
    orch = make_orchestrator(client, runner=make_runner(calls=calls), only=["mayo_diseases"])
    manifest = orch.run()

    # --only re-runs the named source even though it was completed.
    assert len(calls) == 1
    assert "diseases_conditions.py" in calls[0][1]
    statuses = {s.name: s.status for s in manifest.sources}
    assert statuses["mayo_diseases"] == "completed"
    # Other previously-completed sources are carried forward, not skipped-this-run.
    assert statuses["huggingface"] == "completed"


def test_skip_downloaders_preserves_prior_downloader_state() -> None:
    client = FakeClient()
    make_orchestrator(client).run()  # all complete and recorded

    # Re-run scrapers only; downloader entries must survive in the manifest.
    calls: list[list[str]] = []
    orch = make_orchestrator(client, runner=make_runner(calls=calls), skip_downloaders=True)
    manifest = orch.run()

    statuses = {s.name: s.status for s in manifest.sources}
    assert "knowledge_graphs" in statuses  # carried forward
    assert statuses["knowledge_graphs"] == "completed"
    # No downloader command ran this time.
    assert not any("downloaders/" in cmd[1] for cmd in calls)


# ──────────────────────────────────────────────────────────────────────────
# Dry run
# ──────────────────────────────────────────────────────────────────────────
def test_dry_run_writes_nothing_and_plans() -> None:
    client = FakeClient()
    calls: list[list[str]] = []
    orch = make_orchestrator(client, runner=make_runner(calls=calls), dry_run=True)
    manifest = orch.run()

    assert calls == []  # nothing executed
    assert client.bucket("maisys-data-dev").store == {}  # no manifest, no log
    assert manifest.totals["planned"] == 15


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def _patch_cli(monkeypatch: pytest.MonkeyPatch, client: FakeClient) -> None:
    monkeypatch.setattr(pb.storage, "Client", lambda *a, **k: client)
    monkeypatch.setattr(pb, "_default_secret_checker", lambda name: True)


def test_main_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_cli(monkeypatch, client)
    # Avoid real subprocesses: make the default runner a no-op success.
    monkeypatch.setattr(pb, "_default_runner", lambda cmd: FakeProc(returncode=0))
    rc = pb.main(["--output-bucket", OUTPUT])
    assert rc == 0
    assert "manifests/phase_b_manifest.json" in client.bucket("maisys-data-dev").store


def test_main_partial_failure_exit_one(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_cli(monkeypatch, client)
    monkeypatch.setattr(pb, "_default_runner", make_runner(fail_scripts={"infermedica_scraper.py"}))
    rc = pb.main(["--output-bucket", OUTPUT])
    assert rc == 1


def test_main_prereq_failure_exit_two(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(accessible=False)  # bucket.exists() -> False
    _patch_cli(monkeypatch, client)
    monkeypatch.setattr(pb, "_default_runner", lambda cmd: FakeProc(returncode=0))
    rc = pb.main(["--output-bucket", OUTPUT])
    assert rc == 2


def test_main_bad_uri_exit_two(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_cli(monkeypatch, client)
    assert pb.main(["--output-bucket", "/local/path"]) == 2


def test_main_unknown_only_exit_two(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_cli(monkeypatch, client)
    assert pb.main(["--output-bucket", OUTPUT, "--only", "bogus"]) == 2
