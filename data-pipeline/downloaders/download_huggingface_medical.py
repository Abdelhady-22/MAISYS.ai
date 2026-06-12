"""Download HuggingFace medical datasets to GCS as Parquet (Phase B).

For each dataset in ``datasets_config.DATASETS`` (or a CLI-selected subset) this
script loads the dataset via ``datasets.load_dataset``, writes one Parquet file
per split to
``gs://<bucket>/beta_training/raw_downloads/huggingface/<name>/<split>.parquet``,
and records a per-dataset manifest (``_manifest.json``) plus an aggregate
manifest at ``gs://<bucket>/manifests/hf_datasets_manifest.json``.

It is idempotent: a dataset is skipped when its per-dataset manifest already
records the current hub revision (``version_hash``), unless ``--force`` is given.

Usage
-----
    python data-pipeline/downloaders/download_huggingface_medical.py \\
        --output-bucket gs://maisys-data-dev/beta_training/raw_downloads/huggingface \\
        [--datasets medalpaca/medical_meadow_medqa,qiaojin/PubMedQA] \\
        [--parallel 4] [--dry-run] [--force] [--verbose]

Authentication: the HuggingFace token is resolved from the ``hf-token`` secret
in GCP Secret Manager (with an ``HF_TOKEN`` env-var fallback for local dev).

Where it runs: a GCP VM in Phase B. Output is cloud-only; nothing persists on a
laptop.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from google.cloud import storage
from pydantic import BaseModel, Field
from tqdm import tqdm

try:
    # Direct execution (`python .../download_huggingface_medical.py`): the
    # script's own directory is on sys.path, so the sibling import is bare.
    from datasets_config import DatasetSpec, get_datasets
except ModuleNotFoundError:  # pragma: no cover - exercised via package import
    # Imported as part of the ``downloaders`` package (e.g. by pytest).
    from downloaders.datasets_config import DatasetSpec, get_datasets

log = structlog.get_logger()

DatasetStatus = Literal["downloaded", "skipped", "failed"]

# Injectable function types — defaults lazily import heavy/optional libraries so
# the module imports cleanly and tests can substitute fakes.
LoadDatasetFn = Callable[[str, str | None, str | None, bool], Any]
DatasetInfoFn = Callable[[str, str | None], str]


# ──────────────────────────────────────────────────────────────────────────
# Secret resolution (temporary shim)
# ──────────────────────────────────────────────────────────────────────────
def resolve_hf_token() -> str | None:
    """Resolve the HuggingFace token.

    Order: ``HF_TOKEN`` env var (local dev), then the ``hf-token`` secret in GCP
    Secret Manager.

    NOTE: This is a temporary shim. Once ``shared/security`` exists it should be
    replaced by ``shared.security.get_secret("hf-token")`` — the canonical
    credential path per ``data-pipeline/CLAUDE.md``. Returns ``None`` (with a
    warning) when no token can be found; public datasets still download.
    """
    env_token = os.getenv("HF_TOKEN")
    if env_token:
        return env_token

    try:
        from google.cloud import secretmanager
    except ImportError:
        log.warning("secretmanager_unavailable", hint="pip install google-cloud-secret-manager")
        return None

    project = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if not project:
        try:
            import google.auth

            _, project = google.auth.default()
        except Exception as exc:  # noqa: BLE001 - best-effort project discovery
            log.warning("gcp_project_discovery_failed", error=str(exc))
            project = None
    if not project:
        log.warning("no_gcp_project", hint="set GOOGLE_CLOUD_PROJECT")
        return None

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/hf-token/versions/latest"
    response = client.access_secret_version(name=name)
    token: str = response.payload.data.decode("utf-8")
    return token


# ──────────────────────────────────────────────────────────────────────────
# Default (real) data-access functions — lazily import optional libraries
# ──────────────────────────────────────────────────────────────────────────
def _default_load_dataset(
    dataset_id: str, config: str | None, token: str | None, trust_remote_code: bool
) -> Any:
    from datasets import load_dataset

    return load_dataset(dataset_id, config, token=token, trust_remote_code=trust_remote_code)


def _default_dataset_version(dataset_id: str, token: str | None) -> str:
    """Return the dataset's current hub revision (commit sha)."""
    from huggingface_hub import HfApi

    info = HfApi().dataset_info(dataset_id, token=token)
    sha: str | None = getattr(info, "sha", None)
    return sha or "unknown"


# ──────────────────────────────────────────────────────────────────────────
# Manifest models
# ──────────────────────────────────────────────────────────────────────────
class DatasetManifest(BaseModel):
    """Per-dataset manifest written to ``<name>/_manifest.json``."""

    dataset_id: str
    name: str
    config: str | None = None
    version_hash: str
    splits: list[str] = Field(default_factory=list)
    row_counts: dict[str, int] = Field(default_factory=dict)
    columns: dict[str, list[str]] = Field(default_factory=dict)
    total_bytes: int = 0
    remote_prefix: str
    parquet_files: list[str] = Field(default_factory=list)
    status: DatasetStatus
    error: str | None = None


class AggregateManifest(BaseModel):
    """Aggregate manifest written to ``manifests/hf_datasets_manifest.json``."""

    run_id: str
    started_at: str
    completed_at: str | None = None
    output_uri: str
    datasets: list[DatasetManifest] = Field(default_factory=list)
    totals: dict[str, int] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────
def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_gs_uri(uri: str) -> tuple[str, str]:
    """Split ``gs://bucket/prefix`` into ``(bucket, prefix)``.

    The prefix may be empty (bucket root) and is returned without a trailing
    slash.
    """
    if not uri.startswith("gs://"):
        raise ValueError(f"not a gs:// URI: {uri!r}")
    without_scheme = uri[len("gs://") :]
    bucket, _, prefix = without_scheme.partition("/")
    if not bucket:
        raise ValueError(f"gs:// URI must include a bucket: {uri!r}")
    return bucket, prefix.strip("/")


def normalize_splits(loaded: Any, spec: DatasetSpec) -> dict[str, Any]:
    """Normalize a ``load_dataset`` result into ``{split_name: dataset}``.

    ``load_dataset`` returns a ``DatasetDict`` (a dict subclass) when no split is
    requested, or a single ``Dataset`` when ``split`` is set.
    """
    if isinstance(loaded, Mapping):
        return dict(loaded)
    return {spec.split or "train": loaded}


# ──────────────────────────────────────────────────────────────────────────
# Downloader
# ──────────────────────────────────────────────────────────────────────────
class HfDownloader:
    """Downloads HuggingFace datasets to GCS as Parquet, producing manifests.

    The storage client and the dataset-access functions are injected so the
    logic can be tested against fakes without contacting GCS or the HF hub.
    """

    def __init__(
        self,
        client: Any,
        output_uri: str,
        *,
        token: str | None = None,
        force: bool = False,
        dry_run: bool = False,
        load_dataset_fn: LoadDatasetFn | None = None,
        version_fn: DatasetInfoFn | None = None,
    ) -> None:
        self.client = client
        self.output_uri = output_uri
        self.bucket_name, self.prefix = parse_gs_uri(output_uri)
        self.bucket = client.bucket(self.bucket_name)
        self.token = token
        self.force = force
        self.dry_run = dry_run
        # Resolve defaults at runtime (not as bound default args) so tests can
        # monkeypatch the module-level functions and main() picks them up.
        self.load_dataset_fn = load_dataset_fn or _default_load_dataset
        self.version_fn = version_fn or _default_dataset_version

    # -- path helpers -------------------------------------------------------
    def dataset_prefix(self, spec: DatasetSpec) -> str:
        return f"{self.prefix}/{spec.name}" if self.prefix else spec.name

    def dataset_remote_uri(self, spec: DatasetSpec) -> str:
        return f"gs://{self.bucket_name}/{self.dataset_prefix(spec)}"

    def manifest_object_name(self, spec: DatasetSpec) -> str:
        return f"{self.dataset_prefix(spec)}/_manifest.json"

    # -- manifest IO --------------------------------------------------------
    def existing_manifest(self, spec: DatasetSpec) -> DatasetManifest | None:
        blob = self.bucket.blob(self.manifest_object_name(spec))
        if not blob.exists():
            return None
        try:
            payload = blob.download_as_text()
            return DatasetManifest.model_validate_json(payload)
        except Exception as exc:  # noqa: BLE001 - corrupt manifest -> re-download
            log.warning("manifest_unreadable", dataset=spec.dataset_id, error=str(exc))
            return None

    def write_dataset_manifest(self, spec: DatasetSpec, manifest: DatasetManifest) -> None:
        blob = self.bucket.blob(self.manifest_object_name(spec))
        blob.upload_from_string(
            json.dumps(manifest.model_dump(), indent=2), content_type="application/json"
        )

    # -- core ---------------------------------------------------------------
    def _download_splits(self, spec: DatasetSpec, version: str) -> DatasetManifest:
        loaded = self.load_dataset_fn(
            spec.dataset_id, spec.config, self.token, spec.trust_remote_code
        )
        splits = normalize_splits(loaded, spec)

        row_counts: dict[str, int] = {}
        columns: dict[str, list[str]] = {}
        parquet_files: list[str] = []
        total_bytes = 0

        for split_name, split_ds in splits.items():
            object_name = f"{self.dataset_prefix(spec)}/{split_name}.parquet"
            tmp = tempfile.NamedTemporaryFile(suffix=".parquet", delete=False)
            tmp.close()
            try:
                split_ds.to_parquet(tmp.name)
                size = os.path.getsize(tmp.name)
                self.bucket.blob(object_name).upload_from_filename(tmp.name)
            finally:
                os.unlink(tmp.name)

            total_bytes += size
            parquet_files.append(f"gs://{self.bucket_name}/{object_name}")
            row_counts[split_name] = _row_count(split_ds)
            columns[split_name] = list(split_ds.column_names)

        return DatasetManifest(
            dataset_id=spec.dataset_id,
            name=spec.name,
            config=spec.config,
            version_hash=version,
            splits=sorted(splits.keys()),
            row_counts=row_counts,
            columns=columns,
            total_bytes=total_bytes,
            remote_prefix=self.dataset_remote_uri(spec),
            parquet_files=sorted(parquet_files),
            status="downloaded",
        )

    def process_dataset(self, spec: DatasetSpec) -> DatasetManifest:
        """Download (or skip) one dataset and return its manifest."""
        try:
            version = self.version_fn(spec.dataset_id, self.token)
            if spec.config:
                version = f"{version}:{spec.config}"
        except Exception as exc:  # noqa: BLE001 - cannot resolve version -> fail this one
            log.error("version_lookup_failed", dataset=spec.dataset_id, error=str(exc))
            return DatasetManifest(
                dataset_id=spec.dataset_id,
                name=spec.name,
                config=spec.config,
                version_hash="unknown",
                remote_prefix=self.dataset_remote_uri(spec),
                status="failed",
                error=f"version lookup failed: {exc}",
            )

        existing = None if self.force else self.existing_manifest(spec)
        if (
            existing is not None
            and existing.status == "downloaded"
            and existing.version_hash == version
        ):
            log.info("skip_existing", dataset=spec.dataset_id, version=version)
            return existing.model_copy(update={"status": "skipped"})

        if self.dry_run:
            log.info("plan_download", dataset=spec.dataset_id, version=version)
            return DatasetManifest(
                dataset_id=spec.dataset_id,
                name=spec.name,
                config=spec.config,
                version_hash=version,
                remote_prefix=self.dataset_remote_uri(spec),
                status="downloaded",
            )

        try:
            manifest = self._download_splits(spec, version)
            self.write_dataset_manifest(spec, manifest)
            log.info(
                "downloaded",
                dataset=spec.dataset_id,
                splits=manifest.splits,
                rows=sum(manifest.row_counts.values()),
                bytes=manifest.total_bytes,
            )
            return manifest
        except Exception as exc:  # noqa: BLE001 - recorded as a failed dataset
            log.error("download_failed", dataset=spec.dataset_id, error=str(exc))
            return DatasetManifest(
                dataset_id=spec.dataset_id,
                name=spec.name,
                config=spec.config,
                version_hash=version,
                remote_prefix=self.dataset_remote_uri(spec),
                status="failed",
                error=str(exc),
            )

    def run(self, specs: list[DatasetSpec], parallel: int) -> AggregateManifest:
        """Process all selected datasets concurrently and assemble the aggregate."""
        aggregate = AggregateManifest(
            run_id=str(uuid.uuid4()),
            started_at=_utc_now_iso(),
            output_uri=self.output_uri,
        )

        results: dict[str, DatasetManifest] = {}
        with (
            tqdm(total=len(specs), desc="datasets", unit="ds") as bar,
            ThreadPoolExecutor(max_workers=parallel) as pool,
        ):
            futures: dict[Future[DatasetManifest], DatasetSpec] = {
                pool.submit(self.process_dataset, spec): spec for spec in specs
            }
            for future in as_completed(futures):
                manifest = future.result()
                results[manifest.dataset_id] = manifest
                bar.update(1)

        # Preserve the canonical inventory order in the aggregate.
        aggregate.datasets = [results[s.dataset_id] for s in specs]
        aggregate.completed_at = _utc_now_iso()
        aggregate.totals = {
            "downloaded": sum(1 for m in aggregate.datasets if m.status == "downloaded"),
            "skipped": sum(1 for m in aggregate.datasets if m.status == "skipped"),
            "failed": sum(1 for m in aggregate.datasets if m.status == "failed"),
            "total_bytes": sum(m.total_bytes for m in aggregate.datasets),
            "total_rows": sum(sum(m.row_counts.values()) for m in aggregate.datasets),
        }
        return aggregate

    def write_aggregate_manifest(self, aggregate: AggregateManifest) -> str:
        """Write the aggregate manifest to ``gs://<bucket>/manifests/...``."""
        object_name = "manifests/hf_datasets_manifest.json"
        uri = f"gs://{self.bucket_name}/{object_name}"
        blob = self.client.bucket(self.bucket_name).blob(object_name)
        blob.upload_from_string(
            json.dumps(aggregate.model_dump(), indent=2), content_type="application/json"
        )
        log.info("aggregate_manifest_written", uri=uri)
        return uri


def _row_count(split_ds: Any) -> int:
    num_rows = getattr(split_ds, "num_rows", None)
    if num_rows is not None:
        return int(num_rows)
    return int(len(split_ds))


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
        prog="download_huggingface_medical",
        description="Download HuggingFace medical datasets to GCS as Parquet.",
    )
    parser.add_argument(
        "--output-bucket",
        required=True,
        help="GCS gs:// URI prefix for dataset output.",
    )
    parser.add_argument(
        "--datasets",
        default=None,
        help="Comma-separated dataset ids/names to fetch (default: all).",
    )
    parser.add_argument("--parallel", type=int, default=4, help="Concurrent downloads.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be downloaded without downloading or writing.",
    )
    parser.add_argument("--force", action="store_true", help="Re-download even if up to date.")
    parser.add_argument("--verbose", action="store_true", help="Debug logging.")
    return parser


def print_summary(aggregate: AggregateManifest, dry_run: bool) -> None:
    label = "DRY RUN" if dry_run else "RUN"
    print(f"\n=== HuggingFace download {label} (run_id={aggregate.run_id}) ===")
    for manifest in aggregate.datasets:
        if dry_run:
            verb = "would skip" if manifest.status == "skipped" else "would download"
            print(f"  {manifest.dataset_id}: {verb} (version={manifest.version_hash})")
        else:
            extra = f" — {manifest.error}" if manifest.error else ""
            rows = sum(manifest.row_counts.values())
            print(
                f"  {manifest.dataset_id}: {manifest.status} "
                f"rows={rows} bytes={manifest.total_bytes}{extra}"
            )
    totals = aggregate.totals
    print(
        f"  TOTAL: downloaded={totals.get('downloaded', 0)} "
        f"skipped={totals.get('skipped', 0)} failed={totals.get('failed', 0)} "
        f"rows={totals.get('total_rows', 0)} bytes={totals.get('total_bytes', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    if args.parallel < 1:
        print("Error: --parallel must be >= 1", file=sys.stderr)
        return 2

    try:
        parse_gs_uri(args.output_bucket)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    names = (
        [n for n in (s.strip() for s in args.datasets.split(",")) if n] if args.datasets else None
    )
    try:
        specs = get_datasets(names)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    token = resolve_hf_token()
    if token is None:
        log.warning("no_hf_token", note="proceeding unauthenticated (public datasets only)")

    client = storage.Client()
    downloader = HfDownloader(
        client,
        args.output_bucket,
        token=token,
        force=args.force,
        dry_run=args.dry_run,
    )

    aggregate = downloader.run(specs, args.parallel)
    if not args.dry_run:
        downloader.write_aggregate_manifest(aggregate)

    print_summary(aggregate, args.dry_run)

    failed = aggregate.totals.get("failed", 0)
    if failed:
        print(f"\n{failed} dataset(s) failed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
