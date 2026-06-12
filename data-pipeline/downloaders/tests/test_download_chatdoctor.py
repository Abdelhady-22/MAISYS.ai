"""Tests for ``download_chatdoctor``.

Neither GitHub nor GCS is contacted: the git runner is injected (it materializes
fake repo files in the clone dir) and an in-memory GCS fake stands in for
``google.cloud.storage`` — per the data-pipeline rule that tests must not depend
on a live external service.

The import below tolerates both layouts: this branch's ``downloaders`` folder is
not yet a package (no ``__init__.py``), but it becomes one once the HuggingFace
downloader work merges. Either way the module under test is importable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

try:  # package layout (downloaders/__init__.py present)
    from downloaders import download_chatdoctor as cd
except ImportError:  # flat layout — put the module's dir on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import download_chatdoctor as cd


# ──────────────────────────────────────────────────────────────────────────
# In-memory GCS fake
# ──────────────────────────────────────────────────────────────────────────
class FakeBlob:
    def __init__(self, bucket: FakeBucket, name: str) -> None:
        self._bucket = bucket
        self.name = name

    def exists(self) -> bool:
        return self.name in self._bucket.store

    def upload_from_string(self, data: str, content_type: str | None = None) -> None:
        self._bucket.store[self.name] = data.encode("utf-8")

    def upload_from_filename(self, filename: str) -> None:
        with open(filename, "rb") as handle:
            self._bucket.store[self.name] = handle.read()

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


# ──────────────────────────────────────────────────────────────────────────
# Fake git runner
# ──────────────────────────────────────────────────────────────────────────
GOOD_RECORDS = [
    {"instruction": "What is a fever?", "input": "", "output": "Elevated body temp."},
    {"instruction": "Define hypertension", "input": "", "output": "High blood pressure."},
]

OUTPUT = "gs://maisys-data-dev/beta_training/raw_downloads/chatdoctor_github"


def make_git_runner(
    *,
    sha: str = "abc1234",
    files: dict[str, Any] | None = None,
    nested: bool = False,
    calls: list[str] | None = None,
    clone_fails: bool = False,
) -> cd.GitRunner:
    """Build a fake git runner.

    On ``clone`` it writes ``files`` (default: both expected datasets with good
    records) into the destination dir; on ``rev-parse`` it returns ``sha``.
    """
    payload = files if files is not None else {name: GOOD_RECORDS for name in cd.EXPECTED_FILES}

    def _runner(args: list[str], cwd: str | None = None) -> str:
        if calls is not None:
            calls.append(" ".join(args))
        if args[0] == "clone":
            if clone_fails:
                raise cd.CloneError("git clone failed: fatal: repository not found")
            dest = Path(args[-1])
            target = dest / "data" if nested else dest
            target.mkdir(parents=True, exist_ok=True)
            for filename, content in payload.items():
                (target / filename).write_text(
                    content if isinstance(content, str) else json.dumps(content),
                    encoding="utf-8",
                )
            return ""
        if args[0] == "-C" and "rev-parse" in args:
            return f"{sha}\n"
        return ""

    return _runner


def make_downloader(
    client: FakeClient, runner: cd.GitRunner, **kwargs: Any
) -> cd.ChatDoctorDownloader:
    return cd.ChatDoctorDownloader(client, OUTPUT, git_runner=runner, **kwargs)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
def test_parse_gs_uri() -> None:
    assert cd.parse_gs_uri("gs://b/p/q") == ("b", "p/q")
    assert cd.parse_gs_uri("gs://b") == ("b", "")
    with pytest.raises(ValueError):
        cd.parse_gs_uri("https://example.com")


def test_validate_records_counts(tmp_path: Path) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps(GOOD_RECORDS), encoding="utf-8")
    assert cd.validate_records(good) == 2


def test_validate_rejects_non_list(tmp_path: Path) -> None:
    bad = tmp_path / "obj.json"
    bad.write_text(json.dumps({"instruction": "x"}), encoding="utf-8")
    with pytest.raises(cd.DatasetValidationError, match="expected a JSON list"):
        cd.validate_records(bad)


def test_validate_rejects_missing_keys(tmp_path: Path) -> None:
    bad = tmp_path / "missing.json"
    bad.write_text(json.dumps([{"instruction": "x", "input": ""}]), encoding="utf-8")
    with pytest.raises(cd.DatasetValidationError, match="missing keys: output"):
        cd.validate_records(bad)


def test_validate_rejects_malformed_json(tmp_path: Path) -> None:
    bad = tmp_path / "broken.json"
    bad.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(cd.DatasetValidationError, match="invalid JSON"):
        cd.validate_records(bad)


# ──────────────────────────────────────────────────────────────────────────
# Full flow
# ──────────────────────────────────────────────────────────────────────────
def test_clone_validate_upload_manifest_flow() -> None:
    client = FakeClient()
    downloader = make_downloader(client, make_git_runner(sha="deadbeef"))
    manifest = downloader.run()

    assert manifest.status == "downloaded"
    assert manifest.commit_sha == "deadbeef"
    assert manifest.total_records == 4  # 2 records x 2 files
    assert {e.filename for e in manifest.files} == set(cd.EXPECTED_FILES)

    store = client.bucket("maisys-data-dev").store
    base = "beta_training/raw_downloads/chatdoctor_github"
    assert f"{base}/HealthCareMagic-100k.json" in store
    assert f"{base}/iCliniq-10k.json" in store
    assert f"{base}/_manifest.json" in store

    written = json.loads(store[f"{base}/_manifest.json"].decode())
    assert written["commit_sha"] == "deadbeef"
    assert written["files"][0]["md5"]  # md5 recorded
    assert written["files"][0]["record_count"] == 2


def test_finds_files_in_nested_dirs() -> None:
    client = FakeClient()
    downloader = make_downloader(client, make_git_runner(nested=True))
    manifest = downloader.run()
    assert manifest.status == "downloaded"
    assert len(manifest.files) == 2


def test_missing_expected_file_raises() -> None:
    client = FakeClient()
    # Only one of the two expected files is present.
    runner = make_git_runner(files={"HealthCareMagic-100k.json": GOOD_RECORDS})
    downloader = make_downloader(client, runner)
    with pytest.raises(cd.DatasetValidationError, match="iCliniq-10k.json"):
        downloader.run()


def test_malformed_dataset_fails_before_upload() -> None:
    client = FakeClient()
    runner = make_git_runner(
        files={
            "HealthCareMagic-100k.json": GOOD_RECORDS,
            "iCliniq-10k.json": "{ broken json",  # raw string, invalid JSON
        }
    )
    downloader = make_downloader(client, runner)
    with pytest.raises(cd.DatasetValidationError):
        downloader.run()
    # Nothing uploaded because validation happens before any upload.
    assert client.bucket("maisys-data-dev").store == {}


def test_clone_failure_propagates() -> None:
    client = FakeClient()
    downloader = make_downloader(client, make_git_runner(clone_fails=True))
    with pytest.raises(cd.CloneError):
        downloader.run()


# ──────────────────────────────────────────────────────────────────────────
# Idempotency
# ──────────────────────────────────────────────────────────────────────────
def test_skip_when_sha_matches() -> None:
    client = FakeClient()
    calls: list[str] = []

    first = make_downloader(client, make_git_runner(sha="v1", calls=calls))
    first.run()
    base = "beta_training/raw_downloads/chatdoctor_github"
    store = client.bucket("maisys-data-dev").store
    assert f"{base}/_manifest.json" in store

    # Drop the data files; a skip must not re-upload them.
    del store[f"{base}/HealthCareMagic-100k.json"]
    del store[f"{base}/iCliniq-10k.json"]

    second = make_downloader(client, make_git_runner(sha="v1", calls=calls))
    manifest = second.run()
    assert manifest.status == "skipped"
    assert f"{base}/HealthCareMagic-100k.json" not in store  # not re-uploaded


def test_sha_change_triggers_redownload() -> None:
    client = FakeClient()
    make_downloader(client, make_git_runner(sha="v1")).run()
    manifest = make_downloader(client, make_git_runner(sha="v2")).run()
    assert manifest.status == "downloaded"
    assert manifest.commit_sha == "v2"


def test_force_redownloads_despite_matching_sha() -> None:
    client = FakeClient()
    make_downloader(client, make_git_runner(sha="v1")).run()
    manifest = make_downloader(client, make_git_runner(sha="v1"), force=True).run()
    assert manifest.status == "downloaded"


def test_dry_run_uploads_nothing() -> None:
    client = FakeClient()
    downloader = make_downloader(client, make_git_runner(sha="v1"), dry_run=True)
    manifest = downloader.run()
    assert manifest.status == "downloaded"  # planned
    assert manifest.total_records == 4
    assert client.bucket("maisys-data-dev").store == {}  # nothing written


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def test_main_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(cd.storage, "Client", lambda *a, **k: client)
    monkeypatch.setattr(cd, "_run_git", make_git_runner(sha="cli1"))
    rc = cd.main(["--output-bucket", OUTPUT])
    assert rc == 0
    base = "beta_training/raw_downloads/chatdoctor_github"
    assert f"{base}/_manifest.json" in client.bucket("maisys-data-dev").store


def test_main_clone_failure_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(cd.storage, "Client", lambda *a, **k: client)
    monkeypatch.setattr(cd, "_run_git", make_git_runner(clone_fails=True))
    rc = cd.main(["--output-bucket", OUTPUT])
    assert rc == 1


def test_main_malformed_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(cd.storage, "Client", lambda *a, **k: client)
    monkeypatch.setattr(
        cd,
        "_run_git",
        make_git_runner(files={name: "bad json" for name in cd.EXPECTED_FILES}),
    )
    rc = cd.main(["--output-bucket", OUTPUT])
    assert rc == 1


def test_main_bad_uri_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(cd.storage, "Client", lambda *a, **k: client)
    rc = cd.main(["--output-bucket", "/local/path"])
    assert rc == 2
