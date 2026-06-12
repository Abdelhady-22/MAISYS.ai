"""Tests for ``download_huggingface_medical``.

Neither GCS nor the HuggingFace hub is contacted. An in-memory GCS fake stands
in for ``google.cloud.storage`` and the ``datasets``/``huggingface_hub`` access
is injected as plain functions returning fakes — per the data-pipeline rule that
tests must not depend on a live external service.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from downloaders import download_huggingface_medical as hf
from downloaders.datasets_config import DATASETS, DatasetSpec, get_datasets


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
# HF dataset fakes
# ──────────────────────────────────────────────────────────────────────────
class FakeDataset:
    def __init__(self, rows: int, columns: list[str]) -> None:
        self.num_rows = rows
        self.column_names = columns

    def to_parquet(self, path: str) -> int:
        with open(path, "wb") as handle:
            handle.write(b"PAR1" + b"x" * self.num_rows)
        return self.num_rows


def make_loader(
    splits: dict[str, FakeDataset],
    *,
    calls: list[str] | None = None,
    fail_for: set[str] | None = None,
) -> hf.LoadDatasetFn:
    def _loader(
        dataset_id: str, config: str | None, token: str | None, trust_remote_code: bool
    ) -> Any:
        if calls is not None:
            calls.append(dataset_id)
        if fail_for and dataset_id in fail_for:
            raise RuntimeError(f"injected load failure for {dataset_id}")
        # Return a fresh dict (DatasetDict is a Mapping) each call.
        return {name: ds for name, ds in splits.items()}

    return _loader


def make_version(version: str = "sha-v1", *, fail_for: set[str] | None = None) -> hf.DatasetInfoFn:
    def _version(dataset_id: str, token: str | None) -> str:
        if fail_for and dataset_id in fail_for:
            raise RuntimeError(f"no info for {dataset_id}")
        return version

    return _version


SPLITS = {"train": FakeDataset(3, ["question", "answer"])}
OUTPUT = "gs://maisys-data-dev/beta_training/raw_downloads/huggingface"


def two_specs() -> list[DatasetSpec]:
    return [
        DatasetSpec(dataset_id="medalpaca/medical_meadow_medqa"),
        DatasetSpec(dataset_id="qiaojin/PubMedQA", config="pqa_artificial"),
    ]


# ──────────────────────────────────────────────────────────────────────────
# Config loading
# ──────────────────────────────────────────────────────────────────────────
def test_get_datasets_defaults_to_all() -> None:
    assert get_datasets(None) == DATASETS
    assert len(get_datasets(None)) == 13


def test_name_sanitization_and_config_suffix() -> None:
    medqa = DatasetSpec(dataset_id="medalpaca/medical_meadow_medqa")
    assert medqa.name == "medalpaca__medical_meadow_medqa"
    pubmed = DatasetSpec(dataset_id="qiaojin/PubMedQA", config="pqa_artificial")
    assert pubmed.name == "qiaojin__PubMedQA__pqa_artificial"


def test_select_by_id_and_by_sanitized_name() -> None:
    by_id = get_datasets(["medalpaca/medical_meadow_medqa"])
    by_name = get_datasets(["medalpaca__medical_meadow_medqa"])
    assert len(by_id) == 1 and by_id == by_name


def test_select_dedupes_repeated_requests() -> None:
    chosen = get_datasets(["medalpaca/medical_meadow_medqa", "medalpaca/medical_meadow_medqa"])
    assert len(chosen) == 1


def test_unknown_dataset_raises() -> None:
    with pytest.raises(ValueError, match="unknown dataset"):
        get_datasets(["nope/not-real"])


def test_parse_gs_uri() -> None:
    assert hf.parse_gs_uri("gs://b/p/q") == ("b", "p/q")
    assert hf.parse_gs_uri("gs://b") == ("b", "")
    with pytest.raises(ValueError):
        hf.parse_gs_uri("s3://b/p")


# ──────────────────────────────────────────────────────────────────────────
# Download behaviour
# ──────────────────────────────────────────────────────────────────────────
def test_full_run_writes_parquet_and_manifests() -> None:
    client = FakeClient()
    downloader = hf.HfDownloader(
        client,
        OUTPUT,
        load_dataset_fn=make_loader(SPLITS),
        version_fn=make_version("sha-v1"),
    )
    aggregate = downloader.run(two_specs(), parallel=2)

    assert aggregate.totals["downloaded"] == 2
    assert aggregate.totals["failed"] == 0
    assert aggregate.totals["total_rows"] == 6  # 3 rows x 2 datasets

    bucket = client.bucket("maisys-data-dev")
    base = "beta_training/raw_downloads/huggingface"
    assert f"{base}/medalpaca__medical_meadow_medqa/train.parquet" in bucket.store
    assert f"{base}/medalpaca__medical_meadow_medqa/_manifest.json" in bucket.store
    # Config-bearing dataset lands under its suffixed folder.
    assert f"{base}/qiaojin__PubMedQA__pqa_artificial/train.parquet" in bucket.store

    # Per-dataset manifest content.
    manifest = json.loads(
        bucket.store[f"{base}/medalpaca__medical_meadow_medqa/_manifest.json"].decode()
    )
    assert manifest["status"] == "downloaded"
    assert manifest["row_counts"] == {"train": 3}
    assert manifest["columns"] == {"train": ["question", "answer"]}
    assert manifest["version_hash"] == "sha-v1"

    # Config is folded into the version hash for the config-bearing dataset.
    pubmed = json.loads(
        bucket.store[f"{base}/qiaojin__PubMedQA__pqa_artificial/_manifest.json"].decode()
    )
    assert pubmed["version_hash"] == "sha-v1:pqa_artificial"

    uri = downloader.write_aggregate_manifest(aggregate)
    assert uri == "gs://maisys-data-dev/manifests/hf_datasets_manifest.json"
    agg = json.loads(bucket.store["manifests/hf_datasets_manifest.json"].decode())
    assert len(agg["datasets"]) == 2


def test_skip_if_manifest_version_matches() -> None:
    client = FakeClient()
    calls: list[str] = []
    spec = DatasetSpec(dataset_id="medalpaca/medical_meadow_medqa")

    # First run downloads.
    d1 = hf.HfDownloader(
        client,
        OUTPUT,
        load_dataset_fn=make_loader(SPLITS, calls=calls),
        version_fn=make_version("sha-v1"),
    )
    d1.run([spec], parallel=1)
    assert calls == ["medalpaca/medical_meadow_medqa"]

    # Second run, same version -> skipped, loader NOT called again.
    d2 = hf.HfDownloader(
        client,
        OUTPUT,
        load_dataset_fn=make_loader(SPLITS, calls=calls),
        version_fn=make_version("sha-v1"),
    )
    agg = d2.run([spec], parallel=1)
    assert calls == ["medalpaca/medical_meadow_medqa"]  # unchanged
    assert agg.totals["skipped"] == 1
    assert agg.totals["downloaded"] == 0


def test_version_change_triggers_redownload() -> None:
    client = FakeClient()
    calls: list[str] = []
    spec = DatasetSpec(dataset_id="medalpaca/medical_meadow_medqa")

    hf.HfDownloader(
        client,
        OUTPUT,
        load_dataset_fn=make_loader(SPLITS, calls=calls),
        version_fn=make_version("sha-v1"),
    ).run([spec], parallel=1)

    # New upstream version -> re-download.
    agg = hf.HfDownloader(
        client,
        OUTPUT,
        load_dataset_fn=make_loader(SPLITS, calls=calls),
        version_fn=make_version("sha-v2"),
    ).run([spec], parallel=1)
    assert calls.count("medalpaca/medical_meadow_medqa") == 2
    assert agg.totals["downloaded"] == 1


def test_force_redownloads_despite_matching_manifest() -> None:
    client = FakeClient()
    calls: list[str] = []
    spec = DatasetSpec(dataset_id="medalpaca/medical_meadow_medqa")

    hf.HfDownloader(
        client,
        OUTPUT,
        load_dataset_fn=make_loader(SPLITS, calls=calls),
        version_fn=make_version("sha-v1"),
    ).run([spec], parallel=1)

    agg = hf.HfDownloader(
        client,
        OUTPUT,
        force=True,
        load_dataset_fn=make_loader(SPLITS, calls=calls),
        version_fn=make_version("sha-v1"),
    ).run([spec], parallel=1)
    assert calls.count("medalpaca/medical_meadow_medqa") == 2
    assert agg.totals["downloaded"] == 1


def test_partial_failure_one_dataset_fails() -> None:
    client = FakeClient()
    specs = two_specs()
    failing = "qiaojin/PubMedQA"
    downloader = hf.HfDownloader(
        client,
        OUTPUT,
        load_dataset_fn=make_loader(SPLITS, fail_for={failing}),
        version_fn=make_version("sha-v1"),
    )
    agg = downloader.run(specs, parallel=2)
    assert agg.totals["downloaded"] == 1
    assert agg.totals["failed"] == 1

    statuses = {m.dataset_id: m.status for m in agg.datasets}
    assert statuses["medalpaca/medical_meadow_medqa"] == "downloaded"
    assert statuses[failing] == "failed"
    failed = next(m for m in agg.datasets if m.dataset_id == failing)
    assert failed.error is not None


def test_version_lookup_failure_marks_failed() -> None:
    client = FakeClient()
    spec = DatasetSpec(dataset_id="medalpaca/medical_meadow_medqa")
    downloader = hf.HfDownloader(
        client,
        OUTPUT,
        load_dataset_fn=make_loader(SPLITS),
        version_fn=make_version(fail_for={spec.dataset_id}),
    )
    agg = downloader.run([spec], parallel=1)
    assert agg.totals["failed"] == 1


def test_dry_run_writes_nothing() -> None:
    client = FakeClient()
    calls: list[str] = []
    downloader = hf.HfDownloader(
        client,
        OUTPUT,
        dry_run=True,
        load_dataset_fn=make_loader(SPLITS, calls=calls),
        version_fn=make_version("sha-v1"),
    )
    agg = downloader.run(two_specs(), parallel=2)
    assert calls == []  # loader never invoked in dry-run
    assert client.bucket("maisys-data-dev").store == {}  # nothing written
    assert agg.totals["downloaded"] == 2  # planned


def test_multi_split_dataset() -> None:
    client = FakeClient()
    splits = {
        "train": FakeDataset(5, ["q", "a"]),
        "test": FakeDataset(2, ["q", "a"]),
    }
    spec = DatasetSpec(dataset_id="medalpaca/medical_meadow_medqa")
    agg = hf.HfDownloader(
        client,
        OUTPUT,
        load_dataset_fn=make_loader(splits),
        version_fn=make_version("sha-v1"),
    ).run([spec], parallel=1)
    m = agg.datasets[0]
    assert sorted(m.splits) == ["test", "train"]
    assert m.row_counts == {"train": 5, "test": 2}
    base = "beta_training/raw_downloads/huggingface/medalpaca__medical_meadow_medqa"
    store = client.bucket("maisys-data-dev").store
    assert f"{base}/train.parquet" in store and f"{base}/test.parquet" in store


# ──────────────────────────────────────────────────────────────────────────
# Secret shim
# ──────────────────────────────────────────────────────────────────────────
def test_resolve_hf_token_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf_local_dev")
    assert hf.resolve_hf_token() == "hf_local_dev"


# ──────────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ──────────────────────────────────────────────────────────────────────────
def _patch_main_deps(
    monkeypatch: pytest.MonkeyPatch,
    client: FakeClient,
    *,
    fail_for: set[str] | None = None,
) -> None:
    monkeypatch.setattr(hf.storage, "Client", lambda *a, **k: client)
    monkeypatch.setattr(hf, "resolve_hf_token", lambda: "tok")
    monkeypatch.setattr(hf, "_default_load_dataset", make_loader(SPLITS, fail_for=fail_for))
    monkeypatch.setattr(hf, "_default_dataset_version", make_version("sha-v1"))


def test_main_real_run_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_main_deps(monkeypatch, client)
    rc = hf.main(["--output-bucket", OUTPUT, "--datasets", "medalpaca/medical_meadow_medqa"])
    assert rc == 0
    assert "manifests/hf_datasets_manifest.json" in client.bucket("maisys-data-dev").store


def test_main_partial_failure_exit_one(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_main_deps(monkeypatch, client, fail_for={"qiaojin/PubMedQA"})
    rc = hf.main(
        [
            "--output-bucket",
            OUTPUT,
            "--datasets",
            "medalpaca/medical_meadow_medqa,qiaojin/PubMedQA",
        ]
    )
    assert rc == 1


def test_main_dry_run_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_main_deps(monkeypatch, client)
    rc = hf.main(["--output-bucket", OUTPUT, "--dry-run"])
    assert rc == 0
    assert client.bucket("maisys-data-dev").store == {}


def test_main_bad_output_uri_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_main_deps(monkeypatch, client)
    rc = hf.main(["--output-bucket", "/not/a/uri"])
    assert rc == 2


def test_main_unknown_dataset_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_main_deps(monkeypatch, client)
    rc = hf.main(["--output-bucket", OUTPUT, "--datasets", "bogus/dataset"])
    assert rc == 2
