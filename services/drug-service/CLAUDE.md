# services/drug-service/

The first vertical slice. Drug information: interactions, dosage, alternatives, pharmacokinetics, comparisons.

## Required Reading

- `docs/technical-guides/part3.md` §10 — drug-service spec, all 12 features, all 8 agents
- `docs/technical-guides/part6.md` §3 — LangGraph agent pattern
- `docs/technical-guides/part6.md` §1 — chunking strategy (medical-aware)
- `docs/technical-guides/part6.md` §2 — dual embedding (MiniLM + PubMedBERT)
- `docs/technical-guides/part5.md` (drug schema) — drugs, interactions, dosages, alternatives, pharmacokinetics, audit
- `services/CLAUDE.md` — all-services standards

## 12 User-Facing Features

1. Drug lookup by name (brand or generic)
2. Drug-drug interactions (pairwise + triplet + N-way)
3. Dosage guidance (adult, pediatric, geriatric, pregnancy, renal/hepatic adjustment)
4. Side effects with prevalence
5. Comparison between drugs (efficacy, side effect profile, cost class)
6. Pharmacokinetics (absorption, distribution, metabolism, excretion)
7. Alternatives (same class, different mechanism, OTC equivalents)
8. Indications & contraindications
9. Mechanism of action
10. Pregnancy/breastfeeding category
11. Drug acquisition info (prescription status, common Egyptian brand names)
12. Web search fallback (Drugs.com via Playwright, for novel drugs not in local data)

## 8 Agents (per Part 3 §10.3)

Each agent is a LangGraph node with structured inputs and outputs. Implemented in `services/drug-service/services/agents/`:

| Agent | File | Purpose |
|---|---|---|
| Lookup Agent | `lookup_agent.py` | Resolve user input → RxNorm CUI |
| Interaction Agent | `interaction_agent.py` | Tier 0 DDIMDL → Tier 1 RAG → Tier 2 web |
| Dosage Agent | `dosage_agent.py` | Population-specific dosage |
| Comparison Agent | `comparison_agent.py` | Side-by-side drug comparison |
| Pharmacokinetics Agent | `pharmacokinetics_agent.py` | ADME details |
| Alternative Agent | `alternative_agent.py` | Same-class and cross-class alternatives |
| Web Search Agent | `web_search_agent.py` | Playwright → Drugs.com fallback |
| Acquisition Agent | `acquisition_agent.py` | Local brand names, prescription status |

## Data Sources

- **DDIMDL** (Postgres `drug.interactions_ddimdl`) — structured drug-drug pairs
- **Drugs.com PDFs** (Qdrant `drug_rag`) — narrative content, dosing tables
- **Mayo drugs** (Qdrant `drug_rag`) — patient-facing info
- **MedlinePlus drugs** (Qdrant `drug_rag`) — patient-facing info
- **RxNorm API** (external) — name normalization

Ingestion order: DDIMDL first (P2-T01), then RAG (P2-T02).

## Tier-Based Retrieval (Interactions)

Per Part 3 §10.4:

1. **Tier 0:** Postgres `interactions_ddimdl` lookup. If hit → return.
2. **Tier 1:** Qdrant `drug_rag` retrieval on "{drug_a} {drug_b} interaction". If confidence > 0.7 → return.
3. **Tier 2:** Web Search Agent → Playwright → Drugs.com interaction checker. Return + cache result back to Postgres for future Tier 0 hits.

## Endpoints

- `POST /drug/lookup` — name → drug record
- `POST /drug/interactions` — N drugs → all pairwise interactions
- `POST /drug/dosage` — drug + population → dosage
- `POST /drug/compare` — 2 drugs → comparison
- `POST /drug/pharmacokinetics` — drug → ADME
- `POST /drug/alternatives` — drug → alternatives
- `POST /drug/acquisition` — drug → local availability
- `POST /drug/search` — natural language query → routes to right agent
- `WS /ws/drug/{request_id}` — progress events during multi-agent flows

## Tables (per Part 5)

- `drugs`
- `drug_synonyms` (brand names, foreign names)
- `interactions_ddimdl`
- `dosages`
- `pharmacokinetics`
- `alternatives`
- `acquisition_info`
- `drug_query_cache`
- `drug_audit_log`

## Dependencies

- Postgres (own database `drug`)
- Redis (KV cache, progress)
- Qdrant (`drug_rag` collection)
- shared/llm_client, shared/embedding, shared/chunking, shared/concurrent
- safety-service (drug-related emergency detection: overdose, allergy)
- translation-service (Arabic responses)
- export-service (PDF reports)

## What This Service Does NOT Do

- No prescriptions. The service informs; clinicians prescribe.
- No personalized dosage recommendations based on a specific patient's labs. Population dosages only, with explicit advice to consult a clinician.
- No purchase facilitation — acquisition info is informational only.
