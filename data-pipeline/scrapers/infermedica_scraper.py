"""Infermedica Engine API scraper, adapted for GCS output (Phase B).

Scrapes the Infermedica Engine API v3 across 7 stages (info, symptoms,
conditions, risk_factors, parse, search, simulated diagnosis interviews) and
writes each output to ``gs://<bucket>/raw/infermedica/`` with a manifest at
``manifests/infermedica_manifest.json``.

The proven API-interaction logic (retry/backoff, group-question answering,
interview simulation, checkpoint resume) is preserved from the staged scraper;
only credentials (→ GCP Secret Manager), output (local disk → GCS), logging
(→ structlog), and the CLI were adapted. The HTTP client and GCS client are
injected so tests run without network or a live bucket.

Credentials: ``infermedica-app-id`` and ``infermedica-app-key`` are read from GCP
Secret Manager (project discovered via ADC). If absent, the script exits with
instructions to create them. Usage::

    python data-pipeline/scrapers/infermedica_scraper.py \\
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
from scrapers._secrets import SecretError, resolve_secret  # noqa: E402
from scrapers._storage import GcsSink, ScraperManifest, parse_gs_uri  # noqa: E402

log = get_logger()

BASE_URL = "https://api.infermedica.com/v3"
RAW_SUBDIR = "raw/infermedica"
MANIFEST_NAME = "infermedica"

DELAY_BETWEEN_REQUESTS = 0.5
BATCH_SIZE = 20
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0
SIMULATION_AGE_SAMPLES = [25, 40, 60]
MAX_INTERVIEW_TURNS = 15

CREATE_HINT = (
    "Create the secrets, then re-run:\n"
    "  gcloud secrets create infermedica-app-id --replication-policy=automatic\n"
    '  echo -n "YOUR_APP_ID"  | gcloud secrets versions add infermedica-app-id  --data-file=-\n'
    "  gcloud secrets create infermedica-app-key --replication-policy=automatic\n"
    '  echo -n "YOUR_APP_KEY" | gcloud secrets versions add infermedica-app-key --data-file=-'
)

HttpClient = (
    Any  # requests-like: .get(url, headers, params, timeout)/.post(url, headers, json, timeout)
)


class InfermedicaScraper:
    """Drives the Infermedica API and writes outputs to GCS.

    Args:
        sink: GCS sink (injected).
        app_id, app_key: API credentials.
        http: requests-like client (injected; defaults to ``requests``).
        sleep: delay function (injected; tests pass a no-op).
        max_seed_symptoms: cap interview seeds (maps to ``--max-pages``).
        force: re-scrape static outputs even if they already exist.
        dry_run: do not call the API or write anything.
    """

    def __init__(
        self,
        sink: GcsSink,
        *,
        app_id: str,
        app_key: str,
        http: HttpClient = None,
        sleep: Callable[[float], None] = time.sleep,
        max_seed_symptoms: int | None = 50,
        force: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.sink = sink
        self.app_id = app_id
        self.app_key = app_key
        self.sleep = sleep
        self.max_seed_symptoms = max_seed_symptoms
        self.force = force
        self.dry_run = dry_run
        self.total_requests = 0
        self.errors: list[dict[str, Any]] = []
        self.manifest = ScraperManifest(
            run_id=str(uuid.uuid4()), area="infermedica", started_at=_utc_now()
        )
        if http is None:
            import requests

            http = requests
        self.http = http

    # -- HTTP ---------------------------------------------------------------
    def _headers(self, interview_id: str | None = None) -> dict[str, str]:
        return {
            "App-Id": self.app_id,
            "App-Key": self.app_key,
            "Content-Type": "application/json",
            "Dev-Mode": "true",
            "Interview-Id": interview_id or str(uuid.uuid4()),
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        interview_id: str | None = None,
    ) -> Any | None:
        if self.dry_run:
            return None
        url = f"{BASE_URL}{path}"
        for attempt in range(1, MAX_RETRIES + 1):
            self.total_requests += 1
            try:
                if method == "GET":
                    resp = self.http.get(
                        url, headers=self._headers(interview_id), params=params, timeout=30
                    )
                else:
                    resp = self.http.post(
                        url, headers=self._headers(interview_id), json=body, timeout=30
                    )
                resp.raise_for_status()
                self.sleep(DELAY_BETWEEN_REQUESTS)
                return resp.json()
            except Exception as exc:  # noqa: BLE001 - retried
                self.errors.append({"endpoint": url, "error": str(exc)})
                log.warning("api_error", method=method, path=path, attempt=attempt, error=str(exc))
                if attempt < MAX_RETRIES:
                    self.sleep(RETRY_BACKOFF**attempt)
        log.error("api_failed", method=method, path=path)
        return None

    def _get(self, path: str, **kw: Any) -> Any | None:
        return self._request("GET", path, **kw)

    def _post(self, path: str, body: dict[str, Any], **kw: Any) -> Any | None:
        return self._request("POST", path, body=body, **kw)

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

    # -- stages -------------------------------------------------------------
    def scrape_info(self) -> dict[str, Any] | None:
        if self._static_exists("info.json"):
            self.manifest.skipped_count += 1
            return None
        data = self._get("/info")
        if data and not self.dry_run:
            self.save("info.json", data)
        return data if isinstance(data, dict) else None

    def scrape_concepts(self, endpoint: str, label: str) -> list[dict[str, Any]]:
        if self._static_exists(f"{label}.json"):
            self.manifest.skipped_count += 1
            return []
        items = self._get(endpoint, params={"age.value": 30}) or []
        enriched: list[dict[str, Any]] = []
        for i, item in enumerate(items):
            if self.dry_run:
                break
            cid = item.get("id", "")
            detail = self._get(f"{endpoint}/{cid}", params={"age.value": 30}) or {}
            enriched.append({**item, **detail})
            if (i + 1) % BATCH_SIZE == 0:
                self.sleep(DELAY_BETWEEN_REQUESTS)
        if not self.dry_run:
            self.save(f"{label}.json", enriched)
        return enriched

    def simulate_interview(self, seed_symptom_id: str, sex: str, age: int) -> dict[str, Any]:
        """Simulate one diagnostic interview (proven answering strategy preserved)."""
        interview_id = str(uuid.uuid4())
        evidence: list[dict[str, Any]] = [
            {"id": seed_symptom_id, "choice_id": "present", "source": "initial"}
        ]
        conversation: list[dict[str, Any]] = []
        final_conditions: list[dict[str, Any]] = []
        last_result: dict[str, Any] | None = None

        for turn in range(MAX_INTERVIEW_TURNS):
            body = {"sex": sex, "age": {"value": age}, "evidence": evidence}
            result = self._post("/diagnosis", body, interview_id=interview_id)
            if not result:
                break
            last_result = result
            question = result.get("question")
            conditions = result.get("conditions", [])
            should_stop = result.get("should_stop", False)
            final_conditions = conditions

            turn_record: dict[str, Any] = {
                "turn": turn + 1,
                "question": None,
                "answer_given": None,
                "conditions_snapshot": [
                    {"id": c["id"], "name": c["name"], "probability": round(c["probability"], 4)}
                    for c in conditions[:5]
                ],
            }

            if question:
                q_type = question.get("type", "")
                items = question.get("items", [])
                new_evidence: list[dict[str, Any]] = []
                answers_given: list[dict[str, Any]] = []
                for idx, item in enumerate(items):
                    choice = (
                        ("present" if idx == 0 else "absent")
                        if q_type == "group_single"
                        else "present"
                    )
                    new_evidence.append({"id": item["id"], "choice_id": choice})
                    answers_given.append(
                        {
                            "symptom_id": item["id"],
                            "symptom_name": item.get("name", ""),
                            "choices_available": [c["label"] for c in item.get("choices", [])],
                            "answer": choice,
                        }
                    )
                turn_record["question"] = {
                    "type": q_type,
                    "text": question.get("text", ""),
                    "items": [{"id": i["id"], "name": i.get("name", "")} for i in items],
                }
                turn_record["answer_given"] = answers_given
                evidence.extend(new_evidence)

            conversation.append(turn_record)
            if should_stop or question is None:
                break

        triage = self._post(
            "/triage",
            {"sex": sex, "age": {"value": age}, "evidence": evidence},
            interview_id=interview_id,
        )
        triage_result = (
            {
                "triage_level": triage.get("triage_level"),
                "teleconsultation_applicable": triage.get("teleconsultation_applicable"),
                "serious": triage.get("serious", []),
            }
            if triage
            else None
        )

        explain_result: dict[str, Any] | None = None
        if final_conditions and final_conditions[0].get("probability", 0) > 0.2:
            top = final_conditions[0]
            explain = self._post(
                "/explain",
                {"sex": sex, "age": {"value": age}, "evidence": evidence, "target": top["id"]},
                interview_id=interview_id,
            )
            if explain:
                explain_result = {
                    "condition_id": top["id"],
                    "condition_name": top["name"],
                    "supporting_evidence": explain.get("supporting_evidence", []),
                    "conflicting_evidence": explain.get("conflicting_evidence", []),
                }

        specialist = self._post(
            "/specialist",
            {"sex": sex, "age": {"value": age}, "evidence": evidence},
            interview_id=interview_id,
        )

        return {
            "interview_id": interview_id,
            "seed_symptom_id": seed_symptom_id,
            "sex": sex,
            "age": age,
            "total_turns": len(conversation),
            "stopped_early": last_result.get("should_stop", False) if last_result else False,
            "final_evidence_count": len(evidence),
            "conversation": conversation,
            "final_diagnosis": [
                {"id": c["id"], "name": c["name"], "probability": round(c["probability"], 4)}
                for c in final_conditions[:10]
            ],
            "triage": triage_result,
            "explain": explain_result,
            "specialist": specialist,
        }

    def scrape_diagnosis_flows(self, symptoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seeds = symptoms[: self.max_seed_symptoms] if self.max_seed_symptoms else symptoms
        combos = [
            (s, sex, age)
            for s in seeds
            for sex in ["male", "female"]
            for age in SIMULATION_AGE_SAMPLES
        ]
        # Resume from a checkpoint object in GCS.
        checkpoint = self.sink.read_json(self._output_name("checkpoint.json")) or {}
        completed: set[str] = (
            set(checkpoint.get("completed", [])) if isinstance(checkpoint, dict) else set()
        )

        flows: list[dict[str, Any]] = []
        existing = self.sink.read_json(self._output_name("diagnosis_flows.json"))
        if isinstance(existing, list):
            flows.extend(existing)

        for symptom, sex, age in combos:
            sid = symptom.get("id", "")
            key = f"{sid}:{sex}:{age}"
            if key in completed:
                continue
            if self.dry_run:
                continue
            flows.append(self.simulate_interview(sid, sex, age))
            completed.add(key)
            if len(completed) % BATCH_SIZE == 0:
                self.sink.write_json(
                    self._output_name("checkpoint.json"), {"completed": sorted(completed)}
                )

        if not self.dry_run:
            self.sink.write_json(
                self._output_name("checkpoint.json"), {"completed": sorted(completed)}
            )
            self.save("diagnosis_flows.json", flows)
        return flows

    def scrape_parse_samples(self) -> list[dict[str, Any]]:
        if self._static_exists("parse_samples.json"):
            self.manifest.skipped_count += 1
            return []
        phrases = [
            "I have a headache and fever",
            "I feel nauseous and my stomach hurts",
            "I have chest pain and shortness of breath",
            "I have a sore throat and cough",
            "I have joint pain and fatigue",
        ]
        results: list[dict[str, Any]] = []
        for phrase in phrases:
            if self.dry_run:
                break
            resp = self._post("/parse", {"text": phrase, "age": {"value": 35}, "sex": "male"})
            if resp:
                results.append({"input_text": phrase, "parsed": resp})
        if not self.dry_run:
            self.save("parse_samples.json", results)
        return results

    def scrape_search_samples(self) -> list[dict[str, Any]]:
        if self._static_exists("search_samples.json"):
            self.manifest.skipped_count += 1
            return []
        terms = ["head", "fever", "pain", "cough", "fatigue"]
        results: list[dict[str, Any]] = []
        for term in terms:
            if self.dry_run:
                break
            resp = self._get(
                "/search",
                params={
                    "phrase": term,
                    "age.value": 35,
                    "sex": "male",
                    "max_results": 20,
                    "type": "symptom",
                },
            )
            if resp:
                results.append({"search_term": term, "results": resp})
        if not self.dry_run:
            self.save("search_samples.json", results)
        return results

    def run(self) -> ScraperManifest:
        self.scrape_info()
        symptoms = self.scrape_concepts("/symptoms", "symptoms")
        self.scrape_concepts("/conditions", "conditions")
        self.scrape_concepts("/risk_factors", "risk_factors")
        self.scrape_parse_samples()
        self.scrape_search_samples()
        self.scrape_diagnosis_flows(symptoms)

        self.manifest.failed_count = len(self.errors)
        self.manifest.completed_at = _utc_now()
        if not self.dry_run:
            self.sink.write_manifest(MANIFEST_NAME, self.manifest)
        return self.manifest


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infermedica_scraper", description="Scrape the Infermedica API to GCS."
    )
    parser.add_argument("--output-bucket", required=True, help="Root GCS gs:// URI.")
    parser.add_argument(
        "--max-pages", type=int, default=50, help="Cap interview seed symptoms (default 50)."
    )
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

    try:
        app_id = resolve_secret("infermedica-app-id", required=True, create_hint=CREATE_HINT)
        app_key = resolve_secret("infermedica-app-key", required=True, create_hint=CREATE_HINT)
    except SecretError as exc:
        print(f"Credentials error: {exc}", file=sys.stderr)
        return 2

    if client is None:
        from google.cloud import storage

        client = storage.Client()
    sink = GcsSink(client, args.output_bucket)
    scraper = InfermedicaScraper(
        sink,
        app_id=app_id or "",
        app_key=app_key or "",
        max_seed_symptoms=args.max_pages,
        force=args.force,
        dry_run=args.dry_run,
    )
    manifest = scraper.run()

    label = "DRY RUN" if args.dry_run else "RUN"
    print(
        f"\n=== Infermedica {label} (run_id={manifest.run_id}) ===\n"
        f"  outputs={manifest.scraped_count} skipped={manifest.skipped_count} "
        f"errors={manifest.failed_count} bytes={manifest.total_bytes}"
    )
    return 1 if manifest.failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
