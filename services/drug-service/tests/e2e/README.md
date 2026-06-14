# E2E test suite — PR3

10 fixture queries (5 English + 5 Arabic) covering every drug-service agent.

## Files

- **`fixtures.json`** — the 10 queries with expected response contracts
- **`runner.py`** — runs each fixture against a live `docker-compose` stack and reports pass/fail

## Running

```bash
# 1. Bring up the full stack
docker-compose up -d postgres redis qdrant auth-service drug-service

# 2. Wait for /readyz
curl -fs http://localhost:8002/readyz | jq

# 3. Seed a test user via auth-service (or use existing dev credentials)
# 4. Run the suite
AUTH_EMAIL=test@maisys.io AUTH_PASSWORD=changeme_local_only \
  python -m services.drug_service.tests.e2e.runner

# Expected output:
#   ✓ e2e-en-01-lookup            agent=lookup           conf=0.91  ok
#   ✓ e2e-en-02-interaction       agent=interaction      conf=0.85  ok
#   ...
#   === E2E result: 9/10 passed (threshold ≥7) ===
```

## What "passing" means

Each fixture's `expected` block declares the contract:

- `primary_agent` — which agent the orchestrator chose
- `visual_type` — which frontend visual hint was emitted
- `min_confidence` — agent's confidence floor
- `min_pairs` / `min_regimens` / `min_rows` / `min_candidates` — agent-specific shape
- `overall_severity_at_least` — interaction-only; floor severity ordering
- `must_contain_metabolism_enzyme` — pharmacokinetics-only; data sanity

A fixture fails if ANY note is recorded. The suite as a whole passes when ≥7/10 fixtures pass (the `PASS_THRESHOLD` default — per the brief's 70% accuracy gate).

## Why NOT pytest?

This runner has external dependencies (live stack, real LLM API, real credentials) that make it unfit for CI parallelism and isolation. Wire it into a manual pre-merge / nightly job instead — unit tests handle the agent contracts; e2e validates real-world accuracy.
