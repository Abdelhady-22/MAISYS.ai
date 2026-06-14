"""End-to-end test runner for the 10 PR3 fixture queries.

Designed to run against a LIVE stack (docker-compose up), not the
unit-test in-memory fakes. The runner:

1. Authenticates against auth-service to get a JWT.
2. For each fixture in ``fixtures.json``:
   a. POSTs ``/drugs/query``.
   b. Asserts the response matches the fixture's ``expected``
      contract (intent → primary_agent, visual_type, etc.).
3. Aggregates a pass/fail table and exits non-zero if any query
   below 70% confidence or with a wrong agent.

Usage::

    # 1. Start the stack
    docker-compose up -d

    # 2. Wait for /readyz
    curl http://localhost:8002/readyz

    # 3. Run the runner with credentials
    AUTH_EMAIL=test@maisys.io AUTH_PASSWORD=… python -m \\
        services.drug_service.tests.e2e.runner

Configuration via env vars:
    DRUG_SERVICE_URL    default http://localhost:8002
    AUTH_SERVICE_URL    default http://localhost:8001
    AUTH_EMAIL          required
    AUTH_PASSWORD       required
    PASS_THRESHOLD      default 7  (out of 10 — need 70% accuracy)

The runner is intentionally NOT a pytest test — it has external
dependencies (live stack, real LLM, real credentials) that make
it unfit for CI. Wire it into a manual nightly job or pre-merge
check instead.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

import httpx

FIXTURES_PATH = Path(__file__).parent / "fixtures.json"

SEVERITY_ORDER = {
    "minor": 0,
    "moderate": 1,
    "major": 2,
    "contraindicated": 3,
}


@dataclass
class FixtureResult:
    fixture_id: str
    passed: bool
    reason: str
    actual_agent: str | None = None
    actual_visual: str | None = None
    actual_confidence: float | None = None
    notes: list[str] = field(default_factory=list)


async def authenticate(
    client: httpx.AsyncClient, auth_url: str, email: str, password: str
) -> str:
    """POST /auth/login → JWT."""
    resp = await client.post(
        f"{auth_url}/auth/login",
        json={"email": email, "password": password},
    )
    resp.raise_for_status()
    body = resp.json()
    if not body.get("success") or "data" not in body:
        raise RuntimeError(f"Login response unexpected shape: {body}")
    return body["data"]["access_token"]


def check_expected(fixture: dict, response: dict) -> tuple[bool, list[str]]:
    """Match the response against the fixture's ``expected`` contract."""
    expected = fixture["expected"]
    notes: list[str] = []

    data = response.get("data", {})
    actual_agent = data.get("primary_agent")
    actual_visual = data.get("visual_type")
    actual_confidence = (data.get("meta") or {}).get("confidence", 0.0)
    citations = data.get("citations", [])
    inner = data.get("data", {})

    if actual_agent != expected.get("primary_agent"):
        notes.append(f"primary_agent mismatch: got {actual_agent!r}, expected {expected['primary_agent']!r}")

    if "visual_type" in expected and actual_visual != expected["visual_type"]:
        notes.append(f"visual_type mismatch: got {actual_visual!r}, expected {expected['visual_type']!r}")

    if actual_confidence < expected.get("min_confidence", 0.0):
        notes.append(f"confidence {actual_confidence:.2f} below min {expected.get('min_confidence')}")

    if "min_citations" in expected and len(citations) < expected["min_citations"]:
        notes.append(f"citations {len(citations)} < min {expected['min_citations']}")

    # Agent-specific shape checks
    if "min_pairs" in expected:
        pairs = inner.get("pairs", [])
        if len(pairs) < expected["min_pairs"]:
            notes.append(f"interaction pairs {len(pairs)} < min {expected['min_pairs']}")

    if "min_regimens" in expected:
        regimens = inner.get("regimens", [])
        if len(regimens) < expected["min_regimens"]:
            notes.append(f"dosage regimens {len(regimens)} < min {expected['min_regimens']}")

    if "min_rows" in expected:
        rows = inner.get("rows", [])
        if len(rows) < expected["min_rows"]:
            notes.append(f"comparison rows {len(rows)} < min {expected['min_rows']}")

    if "min_candidates" in expected:
        candidates = inner.get("candidates", [])
        if len(candidates) < expected["min_candidates"]:
            notes.append(f"alternative candidates {len(candidates)} < min {expected['min_candidates']}")

    if "overall_severity_at_least" in expected:
        actual_sev = inner.get("overall_severity")
        if actual_sev is None or SEVERITY_ORDER.get(actual_sev, -1) < SEVERITY_ORDER.get(expected["overall_severity_at_least"], 0):
            notes.append(
                f"overall_severity {actual_sev!r} below floor {expected['overall_severity_at_least']!r}"
            )

    if "must_contain_metabolism_enzyme" in expected:
        enzymes = (inner.get("metabolism") or {}).get("primary_cyp_enzymes", [])
        if expected["must_contain_metabolism_enzyme"] not in enzymes:
            notes.append(
                f"metabolism enzymes {enzymes} missing {expected['must_contain_metabolism_enzyme']}"
            )

    return (len(notes) == 0, notes)


async def run_one(
    client: httpx.AsyncClient,
    drug_url: str,
    token: str,
    fixture: dict,
) -> FixtureResult:
    try:
        resp = await client.post(
            f"{drug_url}/drugs/query",
            json={"text": fixture["text"], "language": fixture["language"]},
            headers={"Authorization": f"Bearer {token}"},
            timeout=60.0,
        )
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        return FixtureResult(
            fixture_id=fixture["id"],
            passed=False,
            reason=f"HTTP failure: {exc}",
        )

    passed, notes = check_expected(fixture, body)
    data = body.get("data") or {}
    return FixtureResult(
        fixture_id=fixture["id"],
        passed=passed,
        reason="ok" if passed else "; ".join(notes),
        actual_agent=data.get("primary_agent"),
        actual_visual=data.get("visual_type"),
        actual_confidence=(data.get("meta") or {}).get("confidence"),
        notes=notes,
    )


async def main() -> int:
    drug_url = os.environ.get("DRUG_SERVICE_URL", "http://localhost:8002")
    auth_url = os.environ.get("AUTH_SERVICE_URL", "http://localhost:8001")
    email = os.environ.get("AUTH_EMAIL")
    password = os.environ.get("AUTH_PASSWORD")
    pass_threshold = int(os.environ.get("PASS_THRESHOLD", "7"))

    if not (email and password):
        print("ERROR: set AUTH_EMAIL and AUTH_PASSWORD env vars", file=sys.stderr)
        return 2

    fixtures = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))

    async with httpx.AsyncClient() as client:
        token = await authenticate(client, auth_url, email, password)
        results: list[FixtureResult] = []
        for fixture in fixtures:
            r = await run_one(client, drug_url, token, fixture)
            results.append(r)
            mark = "✓" if r.passed else "✗"
            conf = f"{r.actual_confidence:.2f}" if r.actual_confidence is not None else "—"
            print(f"  {mark} {r.fixture_id:<35} agent={r.actual_agent or '—':<16} conf={conf}  {r.reason}")

    n_pass = sum(1 for r in results if r.passed)
    n_total = len(results)
    print(f"\n=== E2E result: {n_pass}/{n_total} passed (threshold ≥{pass_threshold}) ===")
    return 0 if n_pass >= pass_threshold else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
