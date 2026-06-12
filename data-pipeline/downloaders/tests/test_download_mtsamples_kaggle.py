"""Tests for ``download_mtsamples_kaggle``.

Neither GCS, Secret Manager, nor Kaggle is contacted. An in-memory GCS fake
stands in for ``google.cloud.storage`` and the credential/download functions are
injected — per the data-pipeline rule that tests must not depend on a live
external service.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from google.cloud import storage as gcs_storage

from downloaders import download_mtsamples_kaggle as mt

OUTPUT = "gs://maisys-data-dev/beta_training/raw_downloads/mtsamples_kaggle"
DATASET = "tboyle10/medicaltranscriptions"
CREDS = json.dumps({"username": "u", "key": "k"})


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
# Download / credential fakes
# ──────────────────────────────────────────────────────────────────────────
def make_download(
    files: dict[str, str],
    *,
    calls: list[str] | None = None,
    assert_config_dir: bool = False,
) -> mt.DownloadFn:
    """Build a fake download fn that writes ``files`` (name -> CSV text)."""

    def _download(dataset: str, dest_dir: str) -> None:
        if calls is not None:
            calls.append(dataset)
        if assert_config_dir:
            # The credentials must be staged before the download is invoked.
            cfg = os.environ.get("KAGGLE_CONFIG_DIR")
            assert cfg is not None
            assert (Path(cfg) / "kaggle.json").exists()
        for name, content in files.items():
            target = Path(dest_dir) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    return _download


def make_creds(payload: str = CREDS, *, calls: list[str] | None = None) -> mt.CredentialsProvider:
    def _provider() -> str:
        if calls is not None:
            calls.append("creds")
        return payload

    return _provider


def raising_creds() -> str:
    raise mt.KaggleCredentialsError(
        "could not read Kaggle credentials from Secret Manager secret "
        "'kaggle-api-key'.\nCreate the secret from your kaggle.json:\n"
        "  gcloud secrets create kaggle-api-key --data-file=$HOME/.kaggle/kaggle.json"
    )


CSV_ONE = "id,transcription\n1,heart exam\n2,lung exam\n3,knee exam\n"


# ──────────────────────────────────────────────────────────────────────────
# Pure helpers
# ──────────────────────────────────────────────────────────────────────────
def test_parse_gs_uri() -> None:
    assert mt.parse_gs_uri("gs://b/p/q") == ("b", "p/q")
    assert mt.parse_gs_uri("gs://b") == ("b", "")
    with pytest.raises(ValueError):
        mt.parse_gs_uri("s3://b/p")


def test_csv_stats(tmp_path: Path) -> None:
    path = tmp_path / "x.csv"
    path.write_text(CSV_ONE, encoding="utf-8")
    rows, columns = mt.csv_stats(path)
    assert rows == 3
    assert columns == ["id", "transcription"]


def test_csv_stats_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    assert mt.csv_stats(path) == (0, [])


def test_compute_md5_matches_hashlib(tmp_path: Path) -> None:
    import hashlib

    path = tmp_path / "f.csv"
    path.write_bytes(b"abc123")
    assert mt.compute_md5(path) == hashlib.md5(b"abc123").hexdigest()


# ──────────────────────────────────────────────────────────────────────────
# Credential handling
# ──────────────────────────────────────────────────────────────────────────
def test_validate_credentials_ok() -> None:
    mt.validate_credentials(CREDS)  # no raise


def test_validate_credentials_bad_json() -> None:
    with pytest.raises(mt.KaggleCredentialsError, match="not valid JSON"):
        mt.validate_credentials("{not json")


def test_validate_credentials_missing_fields() -> None:
    with pytest.raises(mt.KaggleCredentialsError, match="username"):
        mt.validate_credentials(json.dumps({"username": "u"}))


def test_kaggle_config_dir_writes_and_cleans_up() -> None:
    captured: dict[str, str] = {}
    assert "KAGGLE_CONFIG_DIR" not in os.environ
    with mt.kaggle_config_dir(CREDS) as cfg_dir:
        captured["dir"] = cfg_dir
        cred_path = Path(cfg_dir) / "kaggle.json"
        assert cred_path.exists()
        assert json.loads(cred_path.read_text()) == {"username": "u", "key": "k"}
        assert os.environ["KAGGLE_CONFIG_DIR"] == cfg_dir
    # Cleaned up on exit.
    assert not Path(captured["dir"]).exists()
    assert "KAGGLE_CONFIG_DIR" not in os.environ


def test_kaggle_config_dir_restores_previous_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KAGGLE_CONFIG_DIR", "/preexisting")
    with mt.kaggle_config_dir(CREDS):
        assert os.environ["KAGGLE_CONFIG_DIR"] != "/preexisting"
    assert os.environ["KAGGLE_CONFIG_DIR"] == "/preexisting"


def test_resolve_kaggle_credentials_clear_error_when_secret_unreadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing/unreadable kaggle.json fails with actionable instructions."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj-1")

    class _FakeSMClient:
        def access_secret_version(self, name: str) -> object:
            raise RuntimeError("NotFound: secret does not exist")

    fake_module = type(
        "sm",
        (),
        {"SecretManagerServiceClient": staticmethod(lambda *a, **k: _FakeSMClient())},
    )
    import google.cloud

    monkeypatch.setattr(google.cloud, "secretmanager", fake_module, raising=False)

    with pytest.raises(mt.KaggleCredentialsError) as excinfo:
        mt.resolve_kaggle_credentials()
    message = str(excinfo.value)
    assert "kaggle-api-key" in message
    assert "gcloud secrets create" in message


# ──────────────────────────────────────────────────────────────────────────
# Downloader behaviour
# ──────────────────────────────────────────────────────────────────────────
def test_full_run_uploads_csv_and_manifest() -> None:
    client = FakeClient()
    downloader = mt.MtSamplesDownloader(
        client,
        OUTPUT,
        DATASET,
        credentials_provider=make_creds(),
        download_fn=make_download({"mtsamples.csv": CSV_ONE}, assert_config_dir=True),
    )
    manifest = downloader.run()

    assert manifest.status == "downloaded"
    store = client.bucket("maisys-data-dev").store
    base = "beta_training/raw_downloads/mtsamples_kaggle"
    # Byte count is the actual uploaded size (newline translation is platform
    # dependent), so derive the expectation from the stored object.
    expected_bytes = len(store[f"{base}/mtsamples.csv"])
    assert manifest.totals == {"files": 1, "total_bytes": expected_bytes, "total_rows": 3}

    assert f"{base}/mtsamples.csv" in store
    assert f"{base}/_manifest.json" in store

    entry = manifest.files[0]
    assert entry.filename == "mtsamples.csv"
    assert entry.remote_uri == f"gs://maisys-data-dev/{base}/mtsamples.csv"
    assert entry.row_count == 3
    assert entry.columns == ["id", "transcription"]

    written = json.loads(store[f"{base}/_manifest.json"].decode())
    assert written["status"] == "downloaded"
    assert written["files"][0]["md5"] == entry.md5


def test_multiple_csvs_uploaded() -> None:
    client = FakeClient()
    files = {
        "mtsamples.csv": CSV_ONE,
        "nested/extra.csv": "a,b\n1,2\n",
    }
    downloader = mt.MtSamplesDownloader(
        client,
        OUTPUT,
        DATASET,
        credentials_provider=make_creds(),
        download_fn=make_download(files),
    )
    manifest = downloader.run()
    assert manifest.totals["files"] == 2
    store = client.bucket("maisys-data-dev").store
    base = "beta_training/raw_downloads/mtsamples_kaggle"
    assert f"{base}/mtsamples.csv" in store
    assert f"{base}/nested/extra.csv" in store
    names = {f.filename for f in manifest.files}
    assert names == {"mtsamples.csv", "nested/extra.csv"}


def test_no_csv_raises() -> None:
    client = FakeClient()
    downloader = mt.MtSamplesDownloader(
        client,
        OUTPUT,
        DATASET,
        credentials_provider=make_creds(),
        download_fn=make_download({"readme.txt": "no csv here"}),
    )
    with pytest.raises(mt.NoCsvError, match="no CSV files"):
        downloader.run()


def test_idempotent_skip_when_manifest_present() -> None:
    client = FakeClient()
    creds_calls: list[str] = []
    dl_calls: list[str] = []

    def build() -> mt.MtSamplesDownloader:
        return mt.MtSamplesDownloader(
            client,
            OUTPUT,
            DATASET,
            credentials_provider=make_creds(calls=creds_calls),
            download_fn=make_download({"mtsamples.csv": CSV_ONE}, calls=dl_calls),
        )

    build().run()
    assert dl_calls == [DATASET]

    # Second run: manifest already present -> skip without downloading or even
    # resolving credentials.
    manifest = build().run()
    assert manifest.status == "skipped"
    assert dl_calls == [DATASET]  # unchanged
    assert creds_calls == ["creds"]  # only the first run resolved creds


def test_force_redownloads_despite_manifest() -> None:
    client = FakeClient()
    dl_calls: list[str] = []

    mt.MtSamplesDownloader(
        client,
        OUTPUT,
        DATASET,
        credentials_provider=make_creds(),
        download_fn=make_download({"mtsamples.csv": CSV_ONE}, calls=dl_calls),
    ).run()

    manifest = mt.MtSamplesDownloader(
        client,
        OUTPUT,
        DATASET,
        force=True,
        credentials_provider=make_creds(),
        download_fn=make_download({"mtsamples.csv": CSV_ONE}, calls=dl_calls),
    ).run()
    assert dl_calls == [DATASET, DATASET]
    assert manifest.status == "downloaded"


def test_dry_run_writes_nothing_and_skips_creds() -> None:
    client = FakeClient()
    creds_calls: list[str] = []
    dl_calls: list[str] = []
    downloader = mt.MtSamplesDownloader(
        client,
        OUTPUT,
        DATASET,
        dry_run=True,
        credentials_provider=make_creds(calls=creds_calls),
        download_fn=make_download({"mtsamples.csv": CSV_ONE}, calls=dl_calls),
    )
    manifest = downloader.run()
    assert manifest.status == "downloaded"
    assert dl_calls == []
    assert creds_calls == []
    assert client.bucket("maisys-data-dev").store == {}


def test_run_propagates_credentials_error() -> None:
    client = FakeClient()
    downloader = mt.MtSamplesDownloader(
        client,
        OUTPUT,
        DATASET,
        credentials_provider=raising_creds,
        download_fn=make_download({"mtsamples.csv": CSV_ONE}),
    )
    with pytest.raises(mt.KaggleCredentialsError):
        downloader.run()
    # Nothing uploaded.
    assert client.bucket("maisys-data-dev").store == {}


# ──────────────────────────────────────────────────────────────────────────
# CLI entrypoint
# ──────────────────────────────────────────────────────────────────────────
def _patch_main_deps(
    monkeypatch: pytest.MonkeyPatch,
    client: FakeClient,
    *,
    creds: mt.CredentialsProvider | None = None,
    download: mt.DownloadFn | None = None,
) -> None:
    monkeypatch.setattr(gcs_storage, "Client", lambda *a, **k: client)
    monkeypatch.setattr(mt, "resolve_kaggle_credentials", creds or make_creds())
    monkeypatch.setattr(
        mt, "_default_download", download or make_download({"mtsamples.csv": CSV_ONE})
    )


def test_main_real_run_exit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_main_deps(monkeypatch, client)
    rc = mt.main(["--output-bucket", OUTPUT, "--dataset", DATASET])
    assert rc == 0
    base = "beta_training/raw_downloads/mtsamples_kaggle"
    store = client.bucket("maisys-data-dev").store
    assert f"{base}/mtsamples.csv" in store
    assert f"{base}/_manifest.json" in store


def test_main_missing_credentials_exit_two(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing kaggle.json -> non-zero exit with clear instructions on stderr."""
    client = FakeClient()
    _patch_main_deps(monkeypatch, client, creds=raising_creds)
    rc = mt.main(["--output-bucket", OUTPUT])
    assert rc == 2
    assert client.bucket("maisys-data-dev").store == {}


def test_main_missing_credentials_prints_instructions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = FakeClient()
    _patch_main_deps(monkeypatch, client, creds=raising_creds)
    mt.main(["--output-bucket", OUTPUT])
    err = capsys.readouterr().err
    assert "gcloud secrets create" in err
    assert "kaggle-api-key" in err


def test_main_dry_run_writes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_main_deps(monkeypatch, client)
    rc = mt.main(["--output-bucket", OUTPUT, "--dry-run"])
    assert rc == 0
    assert client.bucket("maisys-data-dev").store == {}


def test_main_bad_output_uri_returns_two(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_main_deps(monkeypatch, client)
    rc = mt.main(["--output-bucket", "/not/a/uri"])
    assert rc == 2


def test_main_no_csv_returns_one(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    _patch_main_deps(monkeypatch, client, download=make_download({"readme.txt": "no csv"}))
    rc = mt.main(["--output-bucket", OUTPUT])
    assert rc == 1
