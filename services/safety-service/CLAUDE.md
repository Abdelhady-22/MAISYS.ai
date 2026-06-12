# services/safety-service/

The safety guardrail every other service consults. Highest priority service in the system.

## Required Reading

- `docs/technical-guides/part2.md` §7 — safety-service spec
- `docs/technical-guides/part4.md` — safety metric targets
- `services/CLAUDE.md` — all-services standards

## Responsibilities

- **Emergency detection** — pattern + LLM classifier identifying emergencies in user input
- **Pediatric modifier** — special handling for input where age < 18
- **Pregnancy modifier** — different drug warnings, different symptom red flags
- **Suicide & self-harm detection** — flag, return safe-messaging response with crisis resources
- **Drug overdose detection** — explicit overdose mentions trigger ER directive
- **PII detection** (light) — flag obvious phone numbers, SSNs, etc. in user input to warn against sharing
- **Output safety post-check** — given a generated response, verify it doesn't contain dangerous claims (e.g., "stop taking your medication")

## Endpoints (Internal — Not Exposed Through Gateway)

- `POST /safety/pre-check` — input text + context → safety verdict + flags
- `POST /safety/post-check` — generated text + context → safety verdict
- `POST /safety/emergency-detect` — fast path, emergency-only
- `GET /safety/crisis-resources/{lang}` — return localized crisis resources (Egypt + bilingual)

## Detection Layers

Per Part 2 §7:

1. **Layer 1 — keyword/regex** — fast, catches the obvious (chest pain, can't breathe, overdose, suicide)
2. **Layer 2 — LLM classifier** — cheap LLM (`shared/llm_client` cheap model) with structured output: `{is_emergency: bool, category: enum, confidence: float}`
3. **Layer 3 — escalation rules** — even if classifier says no, certain combinations always escalate (e.g., child + fever > 39 + neck stiffness)

## Emergency Categories

- `cardiac` — chest pain, irregular heartbeat with symptoms
- `respiratory` — severe shortness of breath
- `stroke` — FAST criteria
- `bleeding` — uncontrolled
- `allergic` — anaphylaxis signs
- `mental_health_crisis` — suicide, self-harm, severe psychotic symptoms
- `pediatric_emergency` — child-specific emergencies (different thresholds)
- `obstetric_emergency` — pregnancy-related emergencies
- `overdose` — drug/medication overdose
- `trauma` — major trauma indicators

Each category has a localized response template (Arabic + English) directing to appropriate care.

## Targets (per Part 4)

- Emergency false negative rate: **0.0%** in evaluation set
- False positive rate: < 5% (we'd rather flag too many than miss one)
- Latency p95 < 200ms (this runs on EVERY request — must be fast)

## Tables (per Part 5)

- `safety_events` (audit log of every detected emergency, anonymized)
- `safety_keyword_lists` (versioned)
- `safety_response_templates`
- `crisis_resources` (per-region, per-language)

## Dependencies

- Postgres (own database `safety`)
- Redis (cache verdicts for identical input within session)
- shared/llm_client (cheap model for classifier)

## What This Service Does NOT Do

- No emergency response coordination (we don't call an ambulance — we tell the user to)
- No real-time location tracking
- No persistent surveillance of user inputs across sessions (each session is independent)
- No moderation in the social-media sense (no content removal — we just flag and respond appropriately)
