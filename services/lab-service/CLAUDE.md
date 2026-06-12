# services/lab-service/

Patient-friendly lab test interpretation. Educational only.

## Required Reading

- `docs/technical-guides/part3.md` §12 — lab-service spec
- `docs/technical-guides/part6.md` §4 — RAG retrieval
- `services/CLAUDE.md` — all-services standards

## Responsibilities

- Lab test catalog (CBC, CMP, lipid panel, thyroid panel, A1c, etc.)
- Value interpretation with reference ranges
- Age, sex, pregnancy adjustments to reference ranges
- Patient-friendly explanations
- Citation to MedlinePlus + Mayo lab sections (`lab_rag` Qdrant collection)
- "What should I ask my doctor?" suggestions

## Endpoints

- `GET /lab/tests` — catalog
- `GET /lab/tests/{id}` — single test details
- `POST /lab/interpret` — submit values + demographics → interpretation
- `POST /lab/explain` — natural language Q about a result
- `WS /ws/lab/{request_id}` — streaming explanation

## Critical Safety Rules

- Critical values (e.g., potassium > 6.5, glucose < 40) → emergency banner: "These values are critical. Contact your doctor or go to the ER immediately."
- Never tell a user to skip medication, change dosage, or delay seeking care based on lab values.
- Always present the interpretation as educational context, with explicit "discuss with your clinician" framing.

## Tables (per Part 5)

- `lab_tests`
- `lab_reference_ranges` (by age, sex, pregnancy status)
- `lab_interpretations` (cached + audit)
- `lab_audit_log`

## Dependencies

- Postgres (own database `lab`)
- Qdrant (`lab_rag` collection — MedlinePlus + Mayo lab content)
- shared/llm_client
- safety-service (critical value detection)
- translation-service

## What This Service Does NOT Do

- No diagnosis from lab values alone.
- No treatment recommendations.
- No drug dosing based on lab values (kidney function-adjusted drug dosing is drug-service's job, and only as population guidance).
