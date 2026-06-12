"""Download medical knowledge graphs to GCS (Phase B).

Three sources (``DATA_PLAN.md`` §2.3, items 35–37), each isolated so one
failing does not abort the others:

* ``primekg``           — Harvard PrimeKG, fetched from the Harvard Dataverse API.
* ``mit_kg``            — MIT Health Knowledge Graph, git-cloned from
  ``clinicalml/HealthKnowledgeGraph``.
* ``itachi9604_neo4j``  — itachi9604 Disease-Symptom (Neo4j-ready), git-cloned
  from ``itachi9604/Disease-Symptom-dataset``.

Each source's files are uploaded under
``gs://<bucket>/knowledge_graphs/<source>/`` with a per-source ``_manifest.json``;
an aggregate manifest is written to
``gs://<bucket>/manifests/knowledge_graphs_manifest.json``.

Idempotent: a source is skipped when its manifest already records the current
version (Dataverse dataset version, or git commit SHA), unless ``--force``.

Usage
-----
    python data-pipeline/downloaders/download_knowledge_graphs.py \\
        --output-bucket gs://maisys-data-dev/knowledge_graphs \\
        [--sources primekg,mit_kg,itachi9604_neo4j] [--dry-run] [--force]

Where it runs: a GCP VM in Phase B. Output is cloud-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import structlog
from google.cloud import storage
from pydantic import BaseModel, Field

log = structlog.get_logger()

DATAVERSE_BASE = "https://dataverse.harvard.edu"
PRIMEKG_DOI = "doi:10.7910/DVN/IXA7BM"
MIT_KG_REPO = "https://github.com/clinicalml/HealthKnowledgeGraph"
ITACHI9604_REPO = "https://github.com/itachi9604/Disease-Symptom-dataset"

# Extensions treated as knowledge-graph payload in git repos.
KG_FILE_SUFFIXES = (".csv", ".tsv", ".json", ".cypher", ".cql")

GitRunner = Callable[[list[str], "str | None"], str]
SourceStatus = Literal["downloaded", "skipped", "failed"]


# ──────────────────────────────────────────────────────────────────────────
# Errors
# ──────────────────────────────────────────────────────────────────────────
class SourceError(Exception):
    """Raised when a single source fails (caught so other sources continue)."""


# ──────────────────────────────────────────────────────────────────────────
# Source + manifest models
# ──────────────────────────────────────────────────────────────────────────
class SourceSpec(BaseModel):
    name: str
    kind: Literal["dataverse", "git"]
    remote_subdir: str
    source_ref: str  # Dataverse DOI or git repo URL


SOURCES: dict[str, SourceSpec] = {
    "primekg": SourceSpec(
        name="primekg",
        kind="dataverse",
        remote_subdir="primekg",
        source_ref=PRIMEKG_DOI,
    ),
    "mit_kg": SourceSpec(
        name="mit_kg",
        kind="git",
        remote_subdir="mit_kg",
        source_ref=MIT_KG_REPO,
    ),
    "itachi9604_neo4j": SourceSpec(
        name="itachi9604_neo4j",
        kind="git",
        remote_subdir="itachi9604_neo4j",
        source_ref=ITACHI9604_REPO,
    ),
}


class KGFileEntry(BaseModel):
    filename: str
    remote_uri: str
    md5: str
    size_bytes: int


class SourceManifest(BaseModel):
    name: str
    kind: str
    source_ref: str
    version_hash: str
    remote_prefix: str
    status: SourceStatus
    files: list[KGFileEntry] = Field(default_factory=list)
    file_count: int = 0
    total_bytes: int = 0
    error: str | None = None


class AggregateManifest(BaseModel):
    run_id: str
    started_at: str
    completed_at: str | None = None
    output_uri: str
    sources: list[SourceManifest] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _run_git(args: list[str], cwd: str | None = None) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        raise SourceError(f"git {' '.join(args)} failed: {stderr or exc}") from exc
    return result.stdout


def parse_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"not a gs:// URI: {uri!r}")
    without_scheme = uri[len("gs://") :]
    bucket, _, prefix = without_scheme.partition("/")
    if not bucket:
        raise ValueError(f"gs:// URI must include a bucket: {uri!r}")
    return bucket, prefix.strip("/")


def resolve_sources(names: list[str] | None) -> list[SourceSpec]:
    """Resolve selected source names to specs (``None`` -> all)."""
    if not names:
        return list(SOURCES.values())
    unknown = [n for n in names if n not in SOURCES]
    if unknown:
        available = ", ".join(SOURCES)
        raise ValueError(f"unknown source(s): {', '.join(unknown)}. Available: {available}")
    # Preserve canonical order, de-duplicated.
    return [spec for key, spec in SOURCES.items() if key in set(names)]


# ──────────────────────────────────────────────────────────────────────────
# Downloader
# ──────────────────────────────────────────────────────────────────────────
class KnowledgeGraphDownloader:
    """Downloads the KG sources to GCS, one isolated source at a time.

    The storage client, HTTP client, and git runner are injected so the flow is
    testable without contacting Dataverse, GitHub, or a live bucket.
    """

    def __init__(
        self,
        client: Any,
        output_uri: str,
        *,
        force: bool = False,
        dry_run: bool = False,
        http_client: Any = None,
        git_runner: GitRunner | None = None,
    ) -> None:
        self.client = client
        self.output_uri = output_uri
        self.bucket_name, self.prefix = parse_gs_uri(output_uri)
        self.bucket = client.bucket(self.bucket_name)
        self.force = force
        self.dry_run = dry_run
        self._http = http_client
        self._owns_http = False
        self.git_runner = git_runner if git_runner is not None else _run_git

    # -- shared helpers -----------------------------------------------------
    def _http_client(self) -> Any:
        if self._http is None:
            import httpx

            self._http = httpx.Client(timeout=60.0, follow_redirects=True)
            self._owns_http = True
        return self._http

    def remote_prefix(self, spec: SourceSpec) -> str:
        return f"{self.prefix}/{spec.remote_subdir}" if self.prefix else spec.remote_subdir

    def remote_prefix_uri(self, spec: SourceSpec) -> str:
        return f"gs://{self.bucket_name}/{self.remote_prefix(spec)}"

    def _manifest_object_name(self, spec: SourceSpec) -> str:
        return f"{self.remote_prefix(spec)}/_manifest.json"

    def existing_manifest(self, spec: SourceSpec) -> SourceManifest | None:
        blob = self.bucket.blob(self._manifest_object_name(spec))
        if not blob.exists():
            return None
        try:
            payload: str = blob.download_as_text()
            return SourceManifest.model_validate_json(payload)
        except Exception as exc:  # noqa: BLE001 - corrupt manifest -> re-download
            log.warning("manifest_unreadable", source=spec.name, error=str(exc))
            return None

    def _maybe_skip(self, spec: SourceSpec, version: str) -> SourceManifest | None:
        if self.force:
            return None
        existing = self.existing_manifest(spec)
        if (
            existing is not None
            and existing.status == "downloaded"
            and existing.version_hash == version
        ):
            log.info("skip_existing", source=spec.name, version=version)
            return existing.model_copy(update={"status": "skipped"})
        return None

    def _upload_bytes(self, object_name: str, data: bytes) -> KGFileEntry:
        self.bucket.blob(object_name).upload_from_string(data)
        return KGFileEntry(
            filename=object_name.rsplit("/", 1)[-1],
            remote_uri=f"gs://{self.bucket_name}/{object_name}",
            md5=hashlib.md5(data).hexdigest(),
            size_bytes=len(data),
        )

    def _planned_manifest(self, spec: SourceSpec, version: str) -> SourceManifest:
        return SourceManifest(
            name=spec.name,
            kind=spec.kind,
            source_ref=spec.source_ref,
            version_hash=version,
            remote_prefix=self.remote_prefix_uri(spec),
            status="downloaded",
        )

    def _finish(self, spec: SourceSpec, version: str, entries: list[KGFileEntry]) -> SourceManifest:
        manifest = SourceManifest(
            name=spec.name,
            kind=spec.kind,
            source_ref=spec.source_ref,
            version_hash=version,
            remote_prefix=self.remote_prefix_uri(spec),
            status="downloaded",
            files=sorted(entries, key=lambda e: e.filename),
            file_count=len(entries),
            total_bytes=sum(e.size_bytes for e in entries),
        )
        self.bucket.blob(self._manifest_object_name(spec)).upload_from_string(
            json.dumps(manifest.model_dump(), indent=2), content_type="application/json"
        )
        log.info("source_done", source=spec.name, files=len(entries), bytes=manifest.total_bytes)
        return manifest

    # -- Dataverse (PrimeKG) ------------------------------------------------
    def _dataverse_files(self, doi: str) -> tuple[str, list[tuple[int, str]]]:
        """Return ``(version, [(file_id, filename), ...])`` for a dataset DOI."""
        url = f"{DATAVERSE_BASE}/api/datasets/:persistentId/?persistentId={doi}"
        response = self._http_client().get(url)
        response.raise_for_status()
        body: dict[str, Any] = response.json()
        version_block: dict[str, Any] = body["data"]["latestVersion"]
        major = version_block.get("versionNumber", 0)
        minor = version_block.get("versionMinorNumber", 0)
        version = f"{major}.{minor}"
        files: list[tuple[int, str]] = []
        for item in version_block.get("files", []):
            data_file = item["dataFile"]
            file_id = int(data_file["id"])
            filename = str(data_file.get("filename") or item.get("label") or f"file_{file_id}")
            files.append((file_id, filename))
        if not files:
            raise SourceError(f"Dataverse dataset {doi} reports no files")
        return version, files

    def _process_dataverse(self, spec: SourceSpec) -> SourceManifest:
        version, files = self._dataverse_files(spec.source_ref)

        skipped = self._maybe_skip(spec, version)
        if skipped is not None:
            return skipped
        if self.dry_run:
            log.info("plan", source=spec.name, version=version, files=[f for _, f in files])
            return self._planned_manifest(spec, version)

        entries: list[KGFileEntry] = []
        http = self._http_client()
        for file_id, filename in files:
            access = f"{DATAVERSE_BASE}/api/access/datafile/{file_id}"
            response = http.get(access)
            response.raise_for_status()
            content: bytes = response.content
            entries.append(self._upload_bytes(f"{self.remote_prefix(spec)}/{filename}", content))
        return self._finish(spec, version, entries)

    # -- Git (MIT KG, itachi9604) ------------------------------------------
    def _git_remote_sha(self, repo_url: str) -> str:
        out = self.git_runner(["ls-remote", repo_url, "HEAD"], None).strip()
        if not out:
            raise SourceError(f"could not resolve remote HEAD for {repo_url}")
        return out.split()[0]

    def _process_git(self, spec: SourceSpec) -> SourceManifest:
        version = self._git_remote_sha(spec.source_ref)

        skipped = self._maybe_skip(spec, version)
        if skipped is not None:
            return skipped
        if self.dry_run:
            log.info("plan", source=spec.name, version=version)
            return self._planned_manifest(spec, version)

        with tempfile.TemporaryDirectory(prefix=f"kg_{spec.name}_") as tmp:
            self.git_runner(["clone", "--depth", "1", spec.source_ref, tmp], None)
            root = Path(tmp)
            kg_files = sorted(
                p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in KG_FILE_SUFFIXES
            )
            if not kg_files:
                raise SourceError(
                    f"{spec.name}: no KG files ({', '.join(KG_FILE_SUFFIXES)}) found in repo"
                )
            entries: list[KGFileEntry] = []
            for path in kg_files:
                rel = path.relative_to(root).as_posix()
                object_name = f"{self.remote_prefix(spec)}/{rel}"
                entries.append(self._upload_bytes(object_name, path.read_bytes()))
        return self._finish(spec, version, entries)

    # -- orchestration ------------------------------------------------------
    def process_source(self, spec: SourceSpec) -> SourceManifest:
        """Process one source; any failure is isolated into a failed manifest."""
        try:
            if spec.kind == "dataverse":
                return self._process_dataverse(spec)
            return self._process_git(spec)
        except Exception as exc:  # noqa: BLE001 - isolate: one source must not kill others
            log.error("source_failed", source=spec.name, error=str(exc))
            return SourceManifest(
                name=spec.name,
                kind=spec.kind,
                source_ref=spec.source_ref,
                version_hash="unknown",
                remote_prefix=self.remote_prefix_uri(spec),
                status="failed",
                error=str(exc),
            )

    def run(self, specs: list[SourceSpec]) -> AggregateManifest:
        aggregate = AggregateManifest(
            run_id=str(uuid.uuid4()),
            started_at=_utc_now_iso(),
            output_uri=self.output_uri,
        )
        try:
            for spec in specs:
                aggregate.sources.append(self.process_source(spec))
        finally:
            if self._owns_http and self._http is not None:
                self._http.close()

        aggregate.completed_at = _utc_now_iso()
        aggregate.totals = {
            "downloaded": sum(1 for s in aggregate.sources if s.status == "downloaded"),
            "skipped": sum(1 for s in aggregate.sources if s.status == "skipped"),
            "failed": sum(1 for s in aggregate.sources if s.status == "failed"),
            "total_files": sum(s.file_count for s in aggregate.sources),
            "total_bytes": sum(s.total_bytes for s in aggregate.sources),
        }
        return aggregate

    def write_aggregate_manifest(self, aggregate: AggregateManifest) -> str:
        object_name = "manifests/knowledge_graphs_manifest.json"
        uri = f"gs://{self.bucket_name}/{object_name}"
        self.client.bucket(self.bucket_name).blob(object_name).upload_from_string(
            json.dumps(aggregate.model_dump(), indent=2), content_type="application/json"
        )
        log.info("aggregate_manifest_written", uri=uri)
        return uri


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def configure_logging(verbose: bool) -> None:
    import logging

    level = logging.DEBUG if verbose else logging.INFO
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(level),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="download_knowledge_graphs",
        description="Download medical knowledge graphs (PrimeKG, MIT KG, itachi9604) to GCS.",
    )
    parser.add_argument("--output-bucket", required=True, help="GCS gs:// URI prefix.")
    parser.add_argument(
        "--sources",
        default=None,
        help="Comma-separated subset of: " + ", ".join(SOURCES) + " (default: all).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="List planned downloads without writing."
    )
    parser.add_argument("--force", action="store_true", help="Re-download even if unchanged.")
    parser.add_argument("--verbose", action="store_true", help="Debug logging.")
    return parser


def print_summary(aggregate: AggregateManifest, dry_run: bool) -> None:
    label = "DRY RUN" if dry_run else "RUN"
    print(f"\n=== Knowledge graph download {label} (run_id={aggregate.run_id}) ===")
    for source in aggregate.sources:
        extra = f" — {source.error}" if source.error else ""
        print(
            f"  {source.name}: {source.status} files={source.file_count} "
            f"bytes={source.total_bytes} version={source.version_hash}{extra}"
        )
    totals = aggregate.totals
    print(
        f"  TOTAL: downloaded={totals.get('downloaded', 0)} "
        f"skipped={totals.get('skipped', 0)} failed={totals.get('failed', 0)} "
        f"files={totals.get('total_files', 0)} bytes={totals.get('total_bytes', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    try:
        parse_gs_uri(args.output_bucket)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    names = [n for n in (s.strip() for s in args.sources.split(",")) if n] if args.sources else None
    try:
        specs = resolve_sources(names)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    client = storage.Client()
    downloader = KnowledgeGraphDownloader(
        client, args.output_bucket, force=args.force, dry_run=args.dry_run
    )
    aggregate = downloader.run(specs)
    if not args.dry_run:
        downloader.write_aggregate_manifest(aggregate)

    print_summary(aggregate, args.dry_run)

    failed = aggregate.totals.get("failed", 0)
    if failed:
        print(f"\n{failed} source(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
