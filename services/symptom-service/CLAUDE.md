# services/symptom-service/

Symptom triage with the Alpha pipeline (Phase 3) and Beta fine-tuned model (Phase 6).

## Required Reading

- `docs/technical-guides/part3.md` §11 — symptom-service spec
- `docs/technical-guides/part4.md` — Beta training & triple-consent protocol
- `docs/technical-guides/part6.md` §3 — agent pattern
- `services/CLAUDE.md` — all-services standards

## Two Pipelines

### Alpha (Phase 3 — implemented first)

External APIs for symptom triage:

- **Infermedica** — primary, well-validated, requires API key
- **EndlessMedical** — secondary, free tier
- Result reconciliation between the two
- Cached per (symptom-set, demographics) for 24h

### Beta (Phase 6 — fine-tuned LLM)

The MAISYS Beta model — a LoRA-fine-tuned LLM trained on ChatDoctor + medical_meadow + MedQA-USMLE + MedMCQA + PubMedQA + diseases dataset. Served via vLLM.

Beta is opt-in and requires **triple consent**:

1. User explicitly enables Beta features in profile
2. User confirms before each Beta-driven triage session
3. User confirms again before seeing Beta output (with reminder that it's experimental)

## Safety-First Rules

Symptom triage is the highest-risk module. Non-negotiable:

- **Emergency detection on every input.** Chest pain, breathing difficulty, stroke symptoms, severe bleeding, suicide ideation, anaphylaxis signs → immediate "go to ER" response, bypass normal flow.
- **Pediatric modifier.** If patient < 18, special handling: stricter emergency thresholds, parent-directed advice.
- **Pregnancy modifier.** Different drug warnings, different red flags.
- **No diagnosis output.** Even with Beta. Output is "possible conditions to discuss with a clinician" + urgency level (routine / soon / urgent / emergency).

## Endpoints

- `POST /symptom/sessions` — start triage session with demographics
- `POST /symptom/sessions/{id}/symptoms` — add symptom, get clarifying questions
- `GET /symptom/sessions/{id}/result` — final triage
- `POST /symptom/sessions/{id}/feedback`
- `WS /ws/symptom/{session_id}` — progress events during multi-step questioning

## Tables (per Part 5)

- `symptom_sessions`
- `symptom_inputs`
- `symptom_questions`
- `triage_results`
- `triage_audit_log`
- `beta_consent_log`

## Dependencies

- Postgres (own database `symptom`)
- Redis (session state, KV cache)
- Infermedica API + EndlessMedical API (Alpha)
- vLLM (Beta, via model-router-service)
- safety-service (emergency detection)
- translation-service

## Beta Metrics Targets (per Part 4)

- Emergency false negative rate: **0.0%**
- Beta triage accuracy: ≥ 87.5%
- Hallucination rate (claims without source): < 1%

If any metric regresses, Beta is auto-disabled service-wide.

## What This Service Does NOT Do

- No diagnosis. Triage to urgency level + possible conditions.
- No prescription recommendations.
- No treatment plans.
- No pediatric or pregnancy advice without the appropriate modifier flag set on the session.
