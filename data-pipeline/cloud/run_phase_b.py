"""Phase B orchestrator: run all scrapers + downloaders on a GCP VM.

Phase B (``DATA_PLAN.md`` §3.3, §5 Phase B) runs every cloud-native scraper and
external downloader on an ephemeral GCP VM, writing output directly to GCS. This
script orchestrates that run:

1. Validates prerequisites (GCS reachable, required secrets present).
2. Runs the scrapers in parallel (Mayo ×4, MedlinePlus ×5, Infermedica,
   EndlessMedical).
3. Runs the downloaders sequentially (HuggingFace, ChatDoctor, MTSamples,
   knowledge graphs).
4. Writes an aggregate ``phase_b_manifest.json`` recording each source's status,
   and a run log to ``logs/phase_b_<run_id>.log``.

Each source is an independent CLI script invoked via ``subprocess``; one failing
does not abort the others. The run is resumable: a re-run skips sources the
existing manifest already records as ``completed`` (use ``--only`` to force a
re-run of specific sources).

Every orchestrated script is invoked as
``python <script> --output-bucket gs://<bucket>/<subpath>`` — the convention all
downloaders already follow (the scraper scripts, P1-T07a–d, are expected to
adopt it). The command registry below is the single place to adjust paths.

Usage
-----
    python data-pipeline/cloud/run_phase_b.py \\
        --output-bucket gs://maisys-data-dev \\
        [--parallel-scrapers 4] [--skip-scrapers] [--skip-downloaders] \\
        [--only mayo_diseases,huggingface] [--dry-run]

Exit codes: 0 = all in-scope sources succeeded; 1 = at least one failed;
2 = prerequisite or usage error (nothing was run).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

import structlog
from google.cloud import storage
from pydantic import BaseModel, Field

log = structlog.get_logger()

REQUIRED_SECRETS = ("hf-token", "kaggle-api-key")
SourceKind = Literal["scraper", "downloader"]
SourceStatus = Literal["completed", "failed", "skipped", "planned"]


class PrerequisiteError(Exception):
    """Raised when a prerequisite check fails (aborts before running anything)."""


class RunResult(Protocol):
    """Structural type for a finished subprocess (matches CompletedProcess)."""

    returncode: int
    stdout: str
    stderr: str


Runner = Callable[[list[str]], RunResult]
SecretChecker = Callable[[str], bool]
BucketChecker = Callable[[], bool]


# ──────────────────────────────────────────────────────────────────────────
# Source registry
# ──────────────────────────────────────────────────────────────────────────
class SourceSpec(BaseModel):
    name: str
    kind: SourceKind
    script: str  # repo-relative path
    remote_subpath: str  # appended to the root output bucket


SCRAPER_SOURCES: list[SourceSpec] = [
    # Mayo Clinic — 4 sub-area scrapers (DATA_PLAN §2.1 #3-6).
    SourceSpec(
        name="mayo_diseases",
        kind="scraper",
        script="data-pipeline/scrapers/mayo_clinic/diseases_conditions.py",
        remote_subpath="raw/mayo_clinic",
    ),
    SourceSpec(
        name="mayo_symptoms",
        kind="scraper",
        script="data-pipeline/scrapers/mayo_clinic/symptoms.py",
        remote_subpath="raw/mayo_clinic",
    ),
    SourceSpec(
        name="mayo_tests",
        kind="scraper",
        script="data-pipeline/scrapers/mayo_clinic/tests_procedures.py",
        remote_subpath="raw/mayo_clinic",
    ),
    SourceSpec(
        name="mayo_drugs",
        kind="scraper",
        script="data-pipeline/scrapers/mayo_clinic/drugs_supplements.py",
        remote_subpath="raw/mayo_clinic",
    ),
    # MedlinePlus — 5 sub-area scrapers (DATA_PLAN §2.1 #7-11).
    SourceSpec(
        name="medlineplus_health_topics",
        kind="scraper",
        script="data-pipeline/scrapers/medlineplus/health_topics.py",
        remote_subpath="raw/medlineplus",
    ),
    SourceSpec(
        name="medlineplus_drugs",
        kind="scraper",
        script="data-pipeline/scrapers/medlineplus/drugs.py",
        remote_subpath="raw/medlineplus",
    ),
    SourceSpec(
        name="medlineplus_lab_tests",
        kind="scraper",
        script="data-pipeline/scrapers/medlineplus/lab_tests.py",
        remote_subpath="raw/medlineplus",
    ),
    SourceSpec(
        name="medlineplus_encyclopedia",
        kind="scraper",
        script="data-pipeline/scrapers/medlineplus/encyclopedia.py",
        remote_subpath="raw/medlineplus",
    ),
    SourceSpec(
        name="medlineplus_genetics",
        kind="scraper",
        script="data-pipeline/scrapers/medlineplus/genetics.py",
        remote_subpath="raw/medlineplus",
    ),
    SourceSpec(
        name="infermedica",
        kind="scraper",
        script="data-pipeline/scrapers/infermedica_scraper.py",
        remote_subpath="raw/infermedica",
    ),
    SourceSpec(
        name="endlessmedical",
        kind="scraper",
        script="data-pipeline/scrapers/endlessmedical_scraper.py",
        remote_subpath="raw/endlessmedical",
    ),
]

DOWNLOADER_SOURCES: list[SourceSpec] = [
    SourceSpec(
        name="huggingface",
        kind="downloader",
        script="data-pipeline/downloaders/download_huggingface_medical.py",
        remote_subpath="beta_training/raw_downloads/huggingface",
    ),
    SourceSpec(
        name="chatdoctor",
        kind="downloader",
        script="data-pipeline/downloaders/download_chatdoctor.py",
        remote_subpath="beta_training/raw_downloads/chatdoctor_github",
    ),
    SourceSpec(
        name="mtsamples",
        kind="downloader",
        script="data-pipeline/downloaders/download_mtsamples_kaggle.py",
        remote_subpath="beta_training/raw_downloads/mtsamples_kaggle",
    ),
    SourceSpec(
        name="knowledge_graphs",
        kind="downloader",
        script="data-pipeline/downloaders/download_knowledge_graphs.py",
        remote_subpath="knowledge_graphs",
    ),
]

ALL_SOURCES: list[SourceSpec] = SCRAPER_SOURCES + DOWNLOADER_SOURCES


# ──────────────────────────────────────────────────────────────────────────
# Manifest models
# ──────────────────────────────────────────────────────────────────────────
class SourceResult(BaseModel):
    name: str
    kind: SourceKind
    status: SourceStatus
    command: str = ""
    output_uri: str = ""
    return_code: int | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: float | None = None
    error: str | None = None


class PhaseBManifest(BaseModel):
    run_id: str
    started_at: str
    completed_at: str | None = None
    output_bucket: str
    sources: list[SourceResult] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_gs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"not a gs:// URI: {uri!r}")
    without_scheme = uri[len("gs://") :]
    bucket, _, prefix = without_scheme.partition("/")
    if not bucket:
        raise ValueError(f"gs:// URI must include a bucket: {uri!r}")
    return bucket, prefix.strip("/")


def _default_runner(cmd: list[str]) -> RunResult:
    return subprocess.run(cmd, capture_output=True, text=True)


def resolve_selection(
    only: list[str] | None, skip_scrapers: bool, skip_downloaders: bool
) -> list[SourceSpec]:
    """Resolve which sources are in scope for this run.

    Raises:
        ValueError: if ``only`` names an unknown source.
    """
    sources = list(ALL_SOURCES)
    if skip_scrapers:
        sources = [s for s in sources if s.kind != "scraper"]
    if skip_downloaders:
        sources = [s for s in sources if s.kind != "downloader"]
    if only:
        known = {s.name for s in ALL_SOURCES}
        unknown = [n for n in only if n not in known]
        if unknown:
            available = ", ".join(s.name for s in ALL_SOURCES)
            raise ValueError(f"unknown source(s): {', '.join(unknown)}. Available: {available}")
        only_set = set(only)
        sources = [s for s in sources if s.name in only_set]
    return sources


# ──────────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────────
class PhaseBOrchestrator:
    """Runs Phase B sources, isolating failures and producing a manifest.

    The storage client, subprocess runner, and prerequisite checkers are
    injected so the orchestration logic can be tested without GCS, real
    subprocesses, or Secret Manager.
    """

    def __init__(
        self,
        client: Any,
        output_bucket: str,
        *,
        parallel_scrapers: int = 4,
        dry_run: bool = False,
        only: list[str] | None = None,
        skip_scrapers: bool = False,
        skip_downloaders: bool = False,
        runner: Runner | None = None,
        bucket_checker: BucketChecker | None = None,
        secret_checker: SecretChecker | None = None,
        python_exe: str = sys.executable,
    ) -> None:
        self.client = client
        self.output_bucket = output_bucket.rstrip("/")
        self.bucket_name, _ = parse_gs_uri(self.output_bucket)
        self.bucket = client.bucket(self.bucket_name)
        self.parallel_scrapers = parallel_scrapers
        self.dry_run = dry_run
        self.only = only
        self.skip_scrapers = skip_scrapers
        self.skip_downloaders = skip_downloaders
        self.runner = runner if runner is not None else _default_runner
        self.bucket_checker = bucket_checker
        self.secret_checker = secret_checker
        self.python_exe = python_exe
        self.run_id = str(uuid.uuid4())
        self.log_lines: list[str] = []

    # -- logging ------------------------------------------------------------
    def _emit(self, event: str, **fields: Any) -> None:
        rendered = " ".join(f"{k}={v}" for k, v in fields.items())
        line = f"{_utc_now_iso()} {event} {rendered}".rstrip()
        print(line)
        self.log_lines.append(line)
        log.info(event, **fields)

    # -- command ------------------------------------------------------------
    def output_uri_for(self, spec: SourceSpec) -> str:
        return f"{self.output_bucket}/{spec.remote_subpath}"

    def command_for(self, spec: SourceSpec) -> list[str]:
        return [self.python_exe, spec.script, "--output-bucket", self.output_uri_for(spec)]

    # -- prerequisites ------------------------------------------------------
    def _check_bucket(self) -> None:
        if self.bucket_checker is not None:
            ok = self.bucket_checker()
        else:
            ok = bool(self.bucket.exists())
        if not ok:
            raise PrerequisiteError(
                f"GCS bucket gs://{self.bucket_name} is not accessible (check ADC / auth)"
            )

    def _check_secrets(self) -> None:
        checker = self.secret_checker or _default_secret_checker
        missing = [name for name in REQUIRED_SECRETS if not checker(name)]
        if missing:
            raise PrerequisiteError(
                f"required secret(s) missing in Secret Manager: {', '.join(missing)}"
            )

    def validate_prerequisites(self) -> None:
        self._emit("prereq_check_start")
        self._check_bucket()
        self._check_secrets()
        self._emit("prereq_check_ok")

    # -- manifest IO --------------------------------------------------------
    def _manifest_object_name(self) -> str:
        return "manifests/phase_b_manifest.json"

    def existing_results(self) -> dict[str, SourceResult]:
        blob = self.bucket.blob(self._manifest_object_name())
        if not blob.exists():
            return {}
        try:
            manifest = PhaseBManifest.model_validate_json(blob.download_as_text())
            return {r.name: r for r in manifest.sources}
        except Exception as exc:  # noqa: BLE001 - corrupt manifest -> start fresh
            self._emit("manifest_unreadable", error=str(exc))
            return {}

    # -- running a single source -------------------------------------------
    def _run_source(self, spec: SourceSpec) -> SourceResult:
        command = self.command_for(spec)
        started = _utc_now_iso()
        clock = time.monotonic()
        try:
            result = self.runner(command)
        except Exception as exc:  # noqa: BLE001 - isolate launch failures
            self._emit("source_error", source=spec.name, error=str(exc))
            return SourceResult(
                name=spec.name,
                kind=spec.kind,
                status="failed",
                command=" ".join(command),
                output_uri=self.output_uri_for(spec),
                started_at=started,
                completed_at=_utc_now_iso(),
                duration_seconds=round(time.monotonic() - clock, 3),
                error=str(exc),
            )

        duration = round(time.monotonic() - clock, 3)
        ok = result.returncode == 0
        if not ok:
            self._emit("source_failed", source=spec.name, rc=result.returncode, duration=duration)
        else:
            self._emit("source_done", source=spec.name, duration=duration)
        return SourceResult(
            name=spec.name,
            kind=spec.kind,
            status="completed" if ok else "failed",
            command=" ".join(command),
            output_uri=self.output_uri_for(spec),
            return_code=result.returncode,
            started_at=started,
            completed_at=_utc_now_iso(),
            duration_seconds=duration,
            error=None if ok else (result.stderr or "").strip()[-500:] or "non-zero exit",
        )

    def _planned(self, spec: SourceSpec) -> SourceResult:
        return SourceResult(
            name=spec.name,
            kind=spec.kind,
            status="planned",
            command=" ".join(self.command_for(spec)),
            output_uri=self.output_uri_for(spec),
        )

    # -- orchestration ------------------------------------------------------
    def run(self) -> PhaseBManifest:
        self.validate_prerequisites()

        selected = resolve_selection(self.only, self.skip_scrapers, self.skip_downloaders)
        existing = self.existing_results()
        results: dict[str, SourceResult] = dict(existing)  # carry forward prior state

        # Decide which selected sources actually run vs resume-skip.
        to_run: list[SourceSpec] = []
        for spec in selected:
            if self.dry_run:
                results[spec.name] = self._planned(spec)
                self._emit("plan", source=spec.name, command=" ".join(self.command_for(spec)))
                continue
            prior = existing.get(spec.name)
            # --only forces a re-run; otherwise skip sources already completed.
            if not self.only and prior is not None and prior.status == "completed":
                self._emit("resume_skip", source=spec.name)
                results[spec.name] = prior.model_copy(update={"status": "skipped"})
                continue
            to_run.append(spec)

        if not self.dry_run:
            scrapers = [s for s in to_run if s.kind == "scraper"]
            downloaders = [s for s in to_run if s.kind == "downloader"]

            # Scrapers run in parallel.
            if scrapers:
                self._emit("scrapers_start", count=len(scrapers), parallel=self.parallel_scrapers)
                with ThreadPoolExecutor(max_workers=self.parallel_scrapers) as pool:
                    for result in pool.map(self._run_source, scrapers):
                        results[result.name] = result

            # Downloaders run sequentially.
            if downloaders:
                self._emit("downloaders_start", count=len(downloaders))
                for spec in downloaders:
                    results[spec.name] = self._run_source(spec)

        manifest = self._build_manifest(results)
        if not self.dry_run:
            self._write_manifest(manifest)
            self._upload_log()
        return manifest

    def _build_manifest(self, results: dict[str, SourceResult]) -> PhaseBManifest:
        # Order by registry, then any extras carried from an older manifest.
        ordered: list[SourceResult] = [results[s.name] for s in ALL_SOURCES if s.name in results]
        known = {s.name for s in ALL_SOURCES}
        ordered.extend(r for name, r in results.items() if name not in known)

        manifest = PhaseBManifest(
            run_id=self.run_id,
            started_at=_utc_now_iso(),
            output_bucket=self.output_bucket,
            sources=ordered,
        )
        manifest.completed_at = _utc_now_iso()
        manifest.totals = {
            "completed": sum(1 for r in ordered if r.status == "completed"),
            "failed": sum(1 for r in ordered if r.status == "failed"),
            "skipped": sum(1 for r in ordered if r.status == "skipped"),
            "planned": sum(1 for r in ordered if r.status == "planned"),
        }
        return manifest

    def _write_manifest(self, manifest: PhaseBManifest) -> str:
        object_name = self._manifest_object_name()
        uri = f"gs://{self.bucket_name}/{object_name}"
        self.bucket.blob(object_name).upload_from_string(
            json.dumps(manifest.model_dump(), indent=2), content_type="application/json"
        )
        self._emit("manifest_written", uri=uri)
        return uri

    def _upload_log(self) -> str:
        object_name = f"logs/phase_b_{self.run_id}.log"
        uri = f"gs://{self.bucket_name}/{object_name}"
        self.bucket.blob(object_name).upload_from_string(
            "\n".join(self.log_lines) + "\n", content_type="text/plain"
        )
        return uri


def _default_secret_checker(name: str) -> bool:
    """Return True if a secret exists in GCP Secret Manager (best effort)."""
    import os

    try:
        from google.cloud import secretmanager
    except ImportError:
        log.warning("secretmanager_unavailable", secret=name)
        return False

    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if not project:
        try:
            import google.auth

            _, project = google.auth.default()
        except Exception as exc:  # noqa: BLE001 - best-effort project discovery
            log.warning("gcp_project_discovery_failed", error=str(exc))
            return False
    if not project:
        return False

    client = secretmanager.SecretManagerServiceClient()
    secret_path = f"projects/{project}/secrets/{name}"
    try:
        client.get_secret(name=secret_path)
        return True
    except Exception:  # noqa: BLE001 - not found / no access -> treat as missing
        return False


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def configure_logging() -> None:
    import logging

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_phase_b",
        description="Orchestrate Phase B scrapers and downloaders on a GCP VM.",
    )
    parser.add_argument("--output-bucket", required=True, help="Root GCS gs:// URI.")
    parser.add_argument(
        "--parallel-scrapers", type=int, default=4, help="Concurrent scrapers (default 4)."
    )
    parser.add_argument("--skip-scrapers", action="store_true", help="Skip all scrapers.")
    parser.add_argument("--skip-downloaders", action="store_true", help="Skip all downloaders.")
    parser.add_argument(
        "--only",
        default=None,
        help="Comma-separated source names to run (forces re-run of those).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="List planned commands without running."
    )
    return parser


def print_summary(manifest: PhaseBManifest, dry_run: bool) -> None:
    label = "DRY RUN" if dry_run else "RUN"
    print(f"\n=== Phase B {label} (run_id={manifest.run_id}) ===")
    for result in manifest.sources:
        extra = f" — {result.error}" if result.error else ""
        print(f"  {result.name} [{result.kind}]: {result.status}{extra}")
    totals = manifest.totals
    print(
        f"  TOTAL: completed={totals.get('completed', 0)} "
        f"failed={totals.get('failed', 0)} skipped={totals.get('skipped', 0)} "
        f"planned={totals.get('planned', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging()

    try:
        parse_gs_uri(args.output_bucket)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.parallel_scrapers < 1:
        print("Error: --parallel-scrapers must be >= 1", file=sys.stderr)
        return 2

    only = [n for n in (s.strip() for s in args.only.split(",")) if n] if args.only else None
    try:
        resolve_selection(only, args.skip_scrapers, args.skip_downloaders)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    client = storage.Client()
    orchestrator = PhaseBOrchestrator(
        client,
        args.output_bucket,
        parallel_scrapers=args.parallel_scrapers,
        dry_run=args.dry_run,
        only=only,
        skip_scrapers=args.skip_scrapers,
        skip_downloaders=args.skip_downloaders,
    )

    try:
        manifest = orchestrator.run()
    except PrerequisiteError as exc:
        log.error("prerequisite_failed", error=str(exc))
        print(f"Prerequisite failed: {exc}", file=sys.stderr)
        return 2

    print_summary(manifest, args.dry_run)

    failed = manifest.totals.get("failed", 0)
    if failed:
        print(f"\n{failed} source(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
