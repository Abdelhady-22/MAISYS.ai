"""Tests for ``download_knowledge_graphs``.

No network, no real clone, no live bucket: httpx, the git runner, and GCS are all
faked/injected — per the data-pipeline rule that tests must not depend on a live
external service.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

try:  # package layout
    from downloaders import download_knowledge_graphs as kg
except ImportError:  # flat layout
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import download_knowledge_graphs as kg


OUTPUT = "gs://maisys-data-dev/knowledge_graphs"


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
# httpx fake (Dataverse)
# ──────────────────────────────────────────────────────────────────────────
class FakeResponse:
    def __init__(self, *, json_data: Any = None, content: bytes = b"", status: int = 200) -> None:
        self._json = json_data
        self.content = content
        self.status_code = status

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeDataverseClient:
    def __init__(
        self,
        *,
        version: tuple[int, int] = (1, 0),
        files: dict[int, str] | None = None,
        fail_meta: bool = False,
        fail_file_ids: set[int] | None = None,
    ) -> None:
        self.version = version
        self.files = files if files is not None else {101: "nodes.csv", 102: "edges.csv"}
        self.contents = {fid: f"content-{fid}".encode() for fid in self.files}
        self.fail_meta = fail_meta
        self.fail_file_ids = fail_file_ids or set()
        self.closed = False
        self.requests: list[str] = []

    def get(self, url: str) -> FakeResponse:
        self.requests.append(url)
        if "/api/datasets/" in url:
            if self.fail_meta:
                return FakeResponse(status=500)
            files = [
                {"label": name, "dataFile": {"id": fid, "filename": name}}
                for fid, name in self.files.items()
            ]
            return FakeResponse(
                json_data={
                    "data": {
                        "latestVersion": {
                            "versionNumber": self.version[0],
                            "versionMinorNumber": self.version[1],
                            "files": files,
                        }
                    }
                }
            )
        if "/api/access/datafile/" in url:
            fid = int(url.rsplit("/", 1)[-1])
            if fid in self.fail_file_ids:
                return FakeResponse(status=500)
            return FakeResponse(content=self.contents[fid])
        return FakeResponse(status=404)

    def close(self) -> None:
        self.closed = True


# ──────────────────────────────────────────────────────────────────────────
# git runner fake
# ──────────────────────────────────────────────────────────────────────────
def make_git_runner(
    *,
    sha: str = "gitsha1",
    files: dict[str, str] | None = None,
    clone_fail_repos: set[str] | None = None,
    ls_remote_fail_repos: set[str] | None = None,
    calls: list[str] | None = None,
) -> kg.GitRunner:
    payload = (
        files
        if files is not None
        else {"graph.csv": "a,b\n1,2\n", "schema.cypher": "CREATE (:N)", "README.md": "ignore"}
    )

    def _runner(args: list[str], cwd: str | None = None) -> str:
        if calls is not None:
            calls.append(" ".join(args))
        if args[0] == "ls-remote":
            repo = args[1]
            if ls_remote_fail_repos and any(r in repo for r in ls_remote_fail_repos):
                raise kg.SourceError(f"ls-remote failed for {repo}")
            return f"{sha}\tHEAD\n"
        if args[0] == "clone":
            repo, dest = args[-2], args[-1]
            if clone_fail_repos and any(r in repo for r in clone_fail_repos):
                raise kg.SourceError(f"clone failed for {repo}")
            for name, content in payload.items():
                (Path(dest) / name).write_text(content, encoding="utf-8")
            return ""
        return ""

    return _runner


def make_downloader(
    client: FakeClient, *, http: Any = None, runner: kg.GitRunner | None = None, **kwargs: Any
) -> kg.KnowledgeGraphDownloader:
    return kg.KnowledgeGraphDownloader(
        client,
        OUTPUT,
        http_client=http if http is not None else FakeDataverseClient(),
        git_runner=runner if runner is not None else make_git_runner(),
        **kwargs,
    )


# ──────────────────────────────────────────────────────────────────────────
# Helpers / config
# ──────────────────────────────────────────────────────────────────────────
def test_parse_gs_uri() -> None:
    assert kg.parse_gs_uri("gs://b/knowledge_graphs") == ("b", "knowledge_graphs")
    with pytest.raises(ValueError):
        kg.parse_gs_uri("http://x")


def test_resolve_sources_default_all() -> None:
    assert [s.name for s in kg.resolve_sources(None)] == [
        "primekg",
        "mit_kg",
        "itachi9604_neo4j",
    ]


def test_resolve_sources_subset_preserves_order() -> None:
    names = [s.name for s in kg.resolve_sources(["itachi9604_neo4j", "primekg"])]
    assert names == ["primekg", "itachi9604_neo4j"]


def test_resolve_sources_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown source"):
        kg.resolve_sources(["primekg", "bogus"])


def test_default_repos_match_data_plan() -> None:
    assert kg.SOURCES["mit_kg"].source_ref.endswith("clinicalml/HealthKnowledgeGraph")
    assert kg.SOURCES["itachi9604_neo4j"].source_ref.endswith("itachi9604/Disease-Symptom-dataset")


# ──────────────────────────────────────────────────────────────────────────
# Full run
# ──────────────────────────────────────────────────────────────────────────
def test_full_run_all_sources() -> None:
    client = FakeClient()
    downloader = make_downloader(client)
    aggregate = downloader.run(kg.resolve_sources(None))

    assert aggregate.totals["downloaded"] == 3
    assert aggregate.totals["failed"] == 0

    store = client.bucket("maisys-data-dev").store
    # PrimeKG via Dataverse
    assert "knowledge_graphs/primekg/nodes.csv" in store
    assert "knowledge_graphs/primekg/edges.csv" in store
    assert "knowledge_graphs/primekg/_manifest.json" in store
    # Git sources: KG files uploaded, README.md filtered out.
    assert "knowledge_graphs/mit_kg/graph.csv" in store
    assert "knowledge_graphs/mit_kg/schema.cypher" in store
    assert "knowledge_graphs/mit_kg/README.md" not in store
    assert "knowledge_graphs/itachi9604_neo4j/graph.csv" in store

    primekg = json.loads(store["knowledge_graphs/primekg/_manifest.json"].decode())
    assert primekg["version_hash"] == "1.0"
    assert primekg["file_count"] == 2
    mit = json.loads(store["knowledge_graphs/mit_kg/_manifest.json"].decode())
    assert mit["version_hash"] == "gitsha1"
    assert mit["file_count"] == 2  # README.md excluded

    uri = downloader.write_aggregate_manifest(aggregate)
    assert uri == "gs://maisys-data-dev/manifests/knowledge_graphs_manifest.json"
    agg = json.loads(store["manifests/knowledge_graphs_manifest.json"].decode())
    assert len(agg["sources"]) == 3


# ──────────────────────────────────────────────────────────────────────────
# Per-source isolation
# ──────────────────────────────────────────────────────────────────────────
def test_dataverse_failure_isolated() -> None:
    client = FakeClient()
    downloader = make_downloader(client, http=FakeDataverseClient(fail_meta=True))
    aggregate = downloader.run(kg.resolve_sources(None))

    statuses = {s.name: s.status for s in aggregate.sources}
    assert statuses["primekg"] == "failed"
    assert statuses["mit_kg"] == "downloaded"
    assert statuses["itachi9604_neo4j"] == "downloaded"
    assert aggregate.totals["failed"] == 1
    assert aggregate.totals["downloaded"] == 2
    # The healthy git sources still produced output.
    assert "knowledge_graphs/mit_kg/graph.csv" in client.bucket("maisys-data-dev").store
    failed = next(s for s in aggregate.sources if s.name == "primekg")
    assert failed.error is not None


def test_one_git_source_failure_isolated() -> None:
    client = FakeClient()
    runner = make_git_runner(clone_fail_repos={"Disease-Symptom-dataset"})
    downloader = make_downloader(client, runner=runner)
    aggregate = downloader.run(kg.resolve_sources(None))

    statuses = {s.name: s.status for s in aggregate.sources}
    assert statuses["primekg"] == "downloaded"
    assert statuses["mit_kg"] == "downloaded"
    assert statuses["itachi9604_neo4j"] == "failed"
    assert aggregate.totals["downloaded"] == 2


def test_git_source_with_no_kg_files_fails() -> None:
    client = FakeClient()
    # Repo contains only a non-KG file.
    runner = make_git_runner(files={"README.md": "nothing here"})
    downloader = make_downloader(client, runner=runner)
    aggregate = downloader.run(kg.resolve_sources(["mit_kg"]))
    assert aggregate.sources[0].status == "failed"
    assert "no KG files" in (aggregate.sources[0].error or "")


def test_dataverse_no_files_fails() -> None:
    client = FakeClient()
    downloader = make_downloader(client, http=FakeDataverseClient(files={}))
    aggregate = downloader.run(kg.resolve_sources(["primekg"]))
    assert aggregate.sources[0].status == "failed"


# ──────────────────────────────────────────────────────────────────────────
# Idempotency
# ──────────────────────────────────────────────────────────────────────────
def test_skip_when_versions_match() -> None:
    client = FakeClient()
    make_downloader(client).run(kg.resolve_sources(None))
    second = make_downloader(client).run(kg.resolve_sources(None))
    assert second.totals["skipped"] == 3
    assert second.totals["downloaded"] == 0


def test_version_change_redownloads_git() -> None:
    client = FakeClient()
    make_downloader(client).run(kg.resolve_sources(["mit_kg"]))
    agg = make_downloader(client, runner=make_git_runner(sha="gitsha2")).run(
        kg.resolve_sources(["mit_kg"])
    )
    assert agg.sources[0].status == "downloaded"
    assert agg.sources[0].version_hash == "gitsha2"


def test_force_redownloads() -> None:
    client = FakeClient()
    make_downloader(client).run(kg.resolve_sources(["primekg"]))
    agg = make_downloader(client, force=True).run(kg.resolve_sources(["primekg"]))
    assert agg.sources[0].status == "downloaded"


def test_dry_run_writes_nothing() -> None:
    client = FakeClient()
    downloader = make_downloader(client, dry_run=True)
    aggregate = downloader.run(kg.resolve_sources(None))
    assert aggregate.totals["downloaded"] == 3  # planned
    assert client.bucket("maisys-data-dev").store == {}


def test_owned_http_client_is_closed() -> None:
    client = FakeClient()
    http = FakeDataverseClient()
    # Injected http client is not owned -> not closed by the downloader.
    downloader = make_downloader(client, http=http)
    downloader.run(kg.resolve_sources(["primekg"]))
    assert http.closed is False


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def test_main_git_source_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(kg.storage, "Client", lambda *a, **k: client)
    monkeypatch.setattr(kg, "_run_git", make_git_runner())
    rc = kg.main(["--output-bucket", OUTPUT, "--sources", "mit_kg"])
    assert rc == 0
    assert "manifests/knowledge_graphs_manifest.json" in client.bucket("maisys-data-dev").store


def test_main_partial_failure_exit_one(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(kg.storage, "Client", lambda *a, **k: client)
    monkeypatch.setattr(kg, "_run_git", make_git_runner())
    # Dataverse fails -> primekg failed, git sources succeed -> exit 1.
    monkeypatch.setattr("httpx.Client", lambda **k: FakeDataverseClient(fail_meta=True))
    rc = kg.main(["--output-bucket", OUTPUT])
    assert rc == 1


def test_main_bad_uri_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kg.storage, "Client", lambda *a, **k: FakeClient())
    assert kg.main(["--output-bucket", "/local"]) == 2


def test_main_unknown_source_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kg.storage, "Client", lambda *a, **k: FakeClient())
    assert kg.main(["--output-bucket", OUTPUT, "--sources", "nope"]) == 2
