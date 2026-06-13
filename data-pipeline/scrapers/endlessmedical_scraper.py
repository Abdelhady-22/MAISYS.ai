"""EndlessMedical API scraper, adapted for GCS output (Phase B).

Scrapes the public EndlessMedical API across 3 stages (features/outcomes,
single-feature seed simulations, multi-feature combo simulations) and writes each
output to ``gs://<bucket>/raw/endlessmedical/`` with a manifest at
``manifests/endlessmedical_manifest.json``.

The proven API-interaction logic (session/ToS handling, retry/backoff, robust
disease parsing, interview simulation, checkpoint resume) is preserved from the
staged scraper; only output (local disk → GCS), logging (→ structlog), and the
CLI were adapted. The HTTP session and GCS client are injected so tests run
without network or a live bucket.

Credentials: the EndlessMedical API is **public** (no key) — it requires only a
Terms-of-Use passphrase, sent per session. An ``endless-medical-api-key`` secret
is read **optionally** (and passed as a header if present), but its absence is
not an error. Usage::

    python data-pipeline/scrapers/endlessmedical_scraper.py \\
        --output-bucket gs://maisys-data-dev [--max-pages N] [--force] [--dry-run]
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import time
import uuid
from collections.abc import Callable
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scrapers._logging import configure_logging, get_logger  # noqa: E402
from scrapers._secrets import resolve_secret  # noqa: E402
from scrapers._storage import GcsSink, ScraperManifest, parse_gs_uri  # noqa: E402

log = get_logger()

BASE_URL = "https://api-prod.endlessmedical.com/v1/dx"
RAW_SUBDIR = "raw/endlessmedical"
MANIFEST_NAME = "endlessmedical"
SECRET_NAME = "endless-medical-api-key"

TERMS_PASSPHRASE = (
    "I have read, understood and I accept and agree to comply with the Terms of Use "
    "of EndlessMedicalAPI and Endless Medical services. "
    "The Terms of Use are available on endlessmedical.com"
)

DELAY_BETWEEN_REQUESTS = 0.6
MAX_TURNS_PER_SESSION = 8
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0

CONTINUOUS_FEATURE_VALUES: dict[str, str] = {
    "Age": "45",
    "Temperature": "38.5",
    "HeartRate": "90",
    "RespiratoryRate": "18",
    "SystolicBP": "130",
    "DiastolicBP": "85",
    "Weight": "75",
    "BMI": "27",
    "SpO2": "96",
    "BloodGlucose": "120",
    "Hemoglobin": "12",
    "WBC": "11",
    "Platelets": "200",
    "Sodium": "138",
    "Potassium": "4.0",
    "Creatinine": "1.0",
}

MULTI_FEATURE_COMBOS: list[list[tuple[str, str]]] = [
    [("Age", "45"), ("Fever", "1"), ("Cough", "1"), ("ShortnessOfBreath", "1")],
    [("Age", "30"), ("Headache", "1"), ("NeckStiffness", "1"), ("Fever", "1")],
    [("Age", "60"), ("ChestPain", "1"), ("ShortnessOfBreath", "1"), ("Sweating", "1")],
    [("Age", "25"), ("AbdominalPain", "1"), ("Nausea", "1"), ("Vomiting", "1")],
    [("Age", "50"), ("Fatigue", "1"), ("WeightLoss", "1"), ("NightSweats", "1")],
    [("Age", "35"), ("JointPain", "1"), ("Rash", "1"), ("Fever", "1")],
    [("Age", "70"), ("Confusion", "1"), ("Fever", "1"), ("DysuriaFrequency", "1")],
    [("Age", "40"), ("Dizziness", "1"), ("Tinnitus", "1"), ("HearingLoss", "1")],
]


def _feature_name(feature: Any) -> str:
    if isinstance(feature, str):
        return feature.strip()
    if isinstance(feature, dict):
        name = feature.get("name") or feature.get("feature") or feature.get("id", "")
        return str(name).strip()
    return str(feature).strip()


def _feature_value(name: str) -> str:
    return CONTINUOUS_FEATURE_VALUES.get(name, "1")


def _parse_disease(d: Any) -> dict[str, Any] | None:
    """Robustly parse one disease entry (handles single-key + explicit-key shapes)."""
    if not isinstance(d, dict):
        return None
    try:
        if "name" in d and "probability" in d:
            return {"disease": str(d["name"]), "probability": float(d["probability"])}
        if len(d) == 1:
            name, prob = next(iter(d.items()))
            return {"disease": str(name), "probability": float(prob)}
        name_keys = ("disease", "condition", "outcome", "label")
        prob_keys = ("probability", "prob", "score", "value", "likelihood")
        name_val = next((d[k] for k in name_keys if k in d), None)
        prob_val = next((d[k] for k in prob_keys if k in d), None)
        if name_val is not None and prob_val is not None:
            return {"disease": str(name_val), "probability": float(prob_val)}
        return None
    except (ValueError, TypeError, StopIteration):
        return None


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


class EndlessMedicalScraper:
    """Drives the EndlessMedical API and writes outputs to GCS."""

    def __init__(
        self,
        sink: GcsSink,
        *,
        session: Any = None,
        api_key: str | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_seed_features: int | None = 50,
        max_turns: int = MAX_TURNS_PER_SESSION,
        force: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.sink = sink
        self.api_key = api_key
        self.sleep = sleep
        self.max_seed_features = max_seed_features
        self.max_turns = max_turns
        self.force = force
        self.dry_run = dry_run
        self.errors: list[dict[str, Any]] = []
        self.manifest = ScraperManifest(
            run_id=str(uuid.uuid4()), area="endlessmedical", started_at=_utc_now()
        )
        if session is None:
            import requests

            session = requests.Session()
        self.session = session

    # -- HTTP ---------------------------------------------------------------
    def _request(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        if self.dry_run:
            return None
        url = f"{BASE_URL}/{path}"
        headers = {"X-Api-Key": self.api_key} if self.api_key else None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = self.session.request(method, url, params=params, headers=headers, timeout=30)
                r.raise_for_status()
                self.sleep(DELAY_BETWEEN_REQUESTS)
                data = r.json()
                if isinstance(data, dict) and data.get("status") == "error":
                    self.errors.append({"endpoint": path, "api_error": data.get("error")})
                    return None
                return data if isinstance(data, dict) else None
            except Exception as exc:  # noqa: BLE001 - retried
                if attempt < MAX_RETRIES:
                    self.sleep(RETRY_BACKOFF * (2 ** (attempt - 1)))
                else:
                    self.errors.append({"endpoint": path, "error": str(exc)})
                    log.error("api_failed", path=path, error=str(exc))
        return None

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self._request("GET", path, params)

    def _post(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self._request("POST", path, params)

    # -- output -------------------------------------------------------------
    def _output_name(self, filename: str) -> str:
        return self.sink.join(RAW_SUBDIR, filename)

    def save(self, filename: str, data: Any) -> None:
        if self.dry_run:
            log.info("plan_save", filename=filename)
            return
        object_name = self._output_name(filename)
        _, size, _ = self.sink.write_json(object_name, data)
        self.manifest.urls.append(self.sink.uri_for(object_name))
        self.manifest.scraped_count += 1
        self.manifest.total_bytes += size
        log.info("saved", filename=filename, bytes=size)

    def _static_exists(self, filename: str) -> bool:
        return not self.force and self.sink.exists(self._output_name(filename))

    # -- session helpers ----------------------------------------------------
    def init_session(self) -> str | None:
        resp = self._get("InitSession")
        if not resp:
            return None
        sid = resp.get("SessionID")
        if not sid:
            return None
        if not self._post(
            "AcceptTermsOfUse", params={"SessionID": sid, "passphrase": TERMS_PASSPHRASE}
        ):
            return None
        return str(sid)

    def update_feature(self, sid: str, name: str, value: str) -> bool:
        return (
            self._post("UpdateFeature", params={"SessionID": sid, "name": name, "value": value})
            is not None
        )

    def get_suggested_patient(self, sid: str) -> list[str]:
        resp = self._get("GetSuggestedFeatures_PatientProvided", params={"SessionID": sid})
        raw = resp.get("SuggestedFeatures", []) if resp else []
        return [_feature_name(s) for s in raw]

    def get_suggested_physician(self, sid: str) -> list[str]:
        resp = self._get("GetSuggestedFeatures_PhysicianProvided", params={"SessionID": sid})
        raw = resp.get("SuggestedFeatures", []) if resp else []
        return [_feature_name(s) for s in raw]

    def get_suggested_tests(self, sid: str) -> list[Any]:
        resp = self._get("GetSuggestedTests", params={"SessionID": sid})
        tests: list[Any] = resp.get("Tests", []) if resp else []
        return tests

    def analyze(self, sid: str) -> dict[str, Any] | None:
        resp = self._get("Analyze", params={"SessionID": sid})
        if not resp:
            return None
        return {
            "diseases": resp.get("Diseases", []),
            "variable_importances": resp.get("VariableImportances", []),
        }

    def _analysis_record(self, result: dict[str, Any]) -> dict[str, Any]:
        parsed = [_parse_disease(d) for d in result["diseases"][:10]]
        return {"top_diseases": [d for d in parsed if d is not None]}

    def _simulate(
        self, sid: str, features_set: dict[str, str]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        conversation: list[dict[str, Any]] = []
        final_analysis: dict[str, Any] | None = None
        for turn in range(self.max_turns):
            turn_record: dict[str, Any] = {"turn": turn + 1}
            patient = self.get_suggested_patient(sid)[:10]
            physician = self.get_suggested_physician(sid)[:10]
            turn_record["suggested_patient_features"] = patient
            turn_record["suggested_physician_features"] = physician
            turn_record["suggested_tests"] = self.get_suggested_tests(sid)[:10]
            result = self.analyze(sid)
            if result:
                final_analysis = result
                turn_record["analysis"] = self._analysis_record(result)
            next_feature = next((f for f in patient if f and f not in features_set), None)
            if next_feature:
                value = _feature_value(next_feature)
                self.update_feature(sid, next_feature, value)
                features_set[next_feature] = value
                turn_record["feature_added"] = {"feature": next_feature, "value": value}
            else:
                turn_record["feature_added"] = None
            conversation.append(turn_record)
            if not patient and not physician:
                break
        return conversation, final_analysis

    # -- stages -------------------------------------------------------------
    def scrape_features(self) -> list[str]:
        if self._static_exists("features.json"):
            self.manifest.skipped_count += 1
            cached = self.sink.read_json(self._output_name("features.json"))
            return cached.get("features", []) if isinstance(cached, dict) else []
        resp = self._get("GetFeatures")
        raw = resp.get("data", []) if resp else []
        features = [n for f in raw if (n := _feature_name(f))]
        if not self.dry_run:
            self.save("features.json", {"count": len(features), "features": features})
        return features

    def scrape_outcomes(self) -> list[str]:
        if self._static_exists("outcomes.json"):
            self.manifest.skipped_count += 1
            return []
        resp = self._get("GetOutcomes")
        raw = resp.get("data", []) if resp else []
        outcomes = [n for o in raw if (n := _feature_name(o))]
        if not self.dry_run:
            self.save("outcomes.json", {"count": len(outcomes), "outcomes": outcomes})
        return outcomes

    def simulate_feature_session(self, feature_name: str) -> dict[str, Any]:
        seed_value = _feature_value(feature_name)
        sid = self.init_session()
        if not sid:
            return {"seed_feature": feature_name, "error": "Failed to init session"}
        features_set: dict[str, str] = {}
        if not self.update_feature(sid, feature_name, seed_value):
            return {"seed_feature": feature_name, "error": "Could not set seed feature"}
        features_set[feature_name] = seed_value
        conversation, final_analysis = self._simulate(sid, features_set)
        return {
            "seed_feature": feature_name,
            "seed_value": seed_value,
            "session_id": sid,
            "features_set": features_set,
            "total_turns": len(conversation),
            "conversation": conversation,
            "final_analysis": final_analysis,
        }

    def scrape_feature_sessions(self, features: list[str]) -> list[dict[str, Any]]:
        if self._static_exists("feature_sessions.json"):
            self.manifest.skipped_count += 1
            return []
        checkpoint = self.sink.read_json(self._output_name("checkpoint.json")) or {}
        completed: list[str] = (
            checkpoint.get("completed", []) if isinstance(checkpoint, dict) else []
        )
        results: list[dict[str, Any]] = (
            checkpoint.get("results", []) if isinstance(checkpoint, dict) else []
        )
        completed_set = set(completed)
        seeds_all = features[: self.max_seed_features] if self.max_seed_features else features
        seeds = [f for f in seeds_all if f not in completed_set]
        for feature in seeds:
            if self.dry_run:
                break
            results.append(self.simulate_feature_session(feature))
            completed.append(feature)
            self.sink.write_json(
                self._output_name("checkpoint.json"), {"completed": completed, "results": results}
            )
        if not self.dry_run:
            self.save("feature_sessions.json", results)
        return results

    def simulate_combo_session(self, combo: list[tuple[str, str]]) -> dict[str, Any]:
        sid = self.init_session()
        if not sid:
            return {"combo_label": str(combo), "error": "Failed to init session"}
        features_set: dict[str, str] = {}
        for name, value in combo:
            if self.update_feature(sid, name, value):
                features_set[name] = value
        conversation, final_analysis = self._simulate(sid, features_set)
        return {
            "combo_label": " | ".join(f"{n}={v}" for n, v in combo),
            "initial_features": dict(combo),
            "session_id": sid,
            "all_features_set": features_set,
            "total_turns": len(conversation),
            "conversation": conversation,
            "final_analysis": final_analysis,
        }

    def scrape_combo_sessions(self) -> list[dict[str, Any]]:
        if self._static_exists("multi_feature_sessions.json"):
            self.manifest.skipped_count += 1
            return []
        results: list[dict[str, Any]] = []
        for combo in MULTI_FEATURE_COMBOS:
            if self.dry_run:
                break
            results.append(self.simulate_combo_session(combo))
        if not self.dry_run:
            self.save("multi_feature_sessions.json", results)
        return results

    def run(self) -> ScraperManifest:
        features = self.scrape_features()
        self.scrape_outcomes()
        self.scrape_feature_sessions(features)
        self.scrape_combo_sessions()
        self.manifest.failed_count = len(self.errors)
        self.manifest.completed_at = _utc_now()
        if not self.dry_run:
            self.sink.write_manifest(MANIFEST_NAME, self.manifest)
        return self.manifest


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="endlessmedical_scraper", description="Scrape the EndlessMedical API to GCS."
    )
    parser.add_argument("--output-bucket", required=True, help="Root GCS gs:// URI.")
    parser.add_argument("--max-pages", type=int, default=50, help="Cap seed features (default 50).")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume (default).")
    parser.add_argument("--force", action="store_true", help="Re-scrape static outputs.")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; no API calls/writes.")
    parser.add_argument("--verbose", action="store_true", help="Debug logging.")
    return parser


def main(argv: list[str] | None = None, *, client: Any = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    try:
        parse_gs_uri(args.output_bucket)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    # The EndlessMedical API is public; the key is optional (passed if present).
    api_key = resolve_secret(SECRET_NAME, required=False)
    if api_key is None:
        log.info("no_api_key", note="proceeding without a key (public API)")

    if client is None:
        from google.cloud import storage

        client = storage.Client()
    sink = GcsSink(client, args.output_bucket)
    scraper = EndlessMedicalScraper(
        sink,
        api_key=api_key,
        max_seed_features=args.max_pages,
        force=args.force,
        dry_run=args.dry_run,
    )
    manifest = scraper.run()

    label = "DRY RUN" if args.dry_run else "RUN"
    print(
        f"\n=== EndlessMedical {label} (run_id={manifest.run_id}) ===\n"
        f"  outputs={manifest.scraped_count} skipped={manifest.skipped_count} "
        f"errors={manifest.failed_count} bytes={manifest.total_bytes}"
    )
    return 1 if manifest.failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
