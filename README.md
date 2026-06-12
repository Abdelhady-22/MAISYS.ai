# MAISYS

**Medical AI System** — a bilingual (Arabic + English) educational platform for medical information access. Built as a graduation project at Benha University, Faculty of Computers and Artificial Intelligence.

> ⚠️ **Not a diagnostic tool.** MAISYS is for education only. All output directs users to qualified clinicians for medical decisions.

---

## What's Inside

Five user-facing modules, each backed by RAG retrieval over authoritative medical sources:

- **Medical Chatbot** — conversational Q&A grounded in Mayo Clinic + MedlinePlus
- **Drug Agent** — interactions, dosage, alternatives, pharmacokinetics (Drugs.com + DDIMDL)
- **Symptom Checker** — Infermedica / EndlessMedical / fine-tuned Beta model
- **Lab Test Explainer** — patient-friendly interpretation of lab values
- **Research Paper Assistant** — RAG over uploaded PDFs

Architecture: 13 microservices + 12 shared library modules, deployed across GCP (dev), Azure (stage), AWS (prod). LangGraph agent orchestration, dual-embedding RAG (MiniLM + PubMedBERT), KV cache, fine-tuned Beta LLM.

---

## Quick Start

This is a working repository. Before you do anything, read these three documents in order:

1. **[`CLAUDE.md`](CLAUDE.md)** — what MAISYS is, the ironclad rules, where to find things
2. **[`YOUR_ROLE.md`](YOUR_ROLE.md)** — what you (the human) do at each task
3. **[`PROGRESS.md`](PROGRESS.md)** — the master task tracker, your daily reference

Then, depending on whether you're starting fresh or jumping in:

- **Starting fresh:** Begin at Phase 0 in `PROGRESS.md`. Follow `YOUR_ROLE.md` §1 for one-time setup.
- **Jumping in:** Find the next `[ ]` task in the current phase. Use `SESSION_PROTOCOL.md` as your Claude Code template.

---

## Repository Map

```
MAISYS.ai/
├── CLAUDE.md                  Project root — identity + rules
├── PROGRESS.md                Master task tracker
├── SESSION_PROTOCOL.md        Claude Code session template
├── YOUR_ROLE.md               Step-by-step human guide
├── DATA_PLAN.md               Cloud data architecture
├── REPO_PLAN.md               This repo's structure and conventions
│
├── docs/                      Frozen reference documentation
│   ├── frontend-guide/
│   └── technical-guides/      Parts 1–6 (architecture, services, schemas, patterns)
│
├── services/                  13 microservices
├── shared/                    12 shared library modules
├── frontend/                  React + TS + Vite + Tailwind + Redux
├── data-pipeline/             Scrapers, downloaders, ingestion, fine-tuning
├── infrastructure/            Terraform for GCP, Azure, AWS
├── k8s/                       Kustomize manifests (base + overlays)
├── monitoring/                Prometheus, Grafana, Loki
└── tests/                     Integration + e2e tests
```

Full structure detail: see [`REPO_PLAN.md`](REPO_PLAN.md).

---

## Stack Summary

- **Backend:** Python 3.11, FastAPI, async SQLAlchemy, Pydantic v2
- **Databases:** Postgres (per service), Redis (cache + pub/sub), Qdrant (vector RAG), RabbitMQ (async tasks)
- **LLM Infrastructure:** LiteLLM, vLLM (Beta model serving), KV cache
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, Redux Toolkit, react-i18next (RTL-aware)
- **Deployment:** Docker, Kubernetes (Kustomize), Terraform, GitHub Actions
- **Observability:** Prometheus, Grafana, Loki

---

## Development Workflow

1. Find the next task in `PROGRESS.md`
2. Read `SESSION_PROTOCOL.md` and follow the template
3. Open Claude Code, paste the filled-in session prompt
4. Stay strictly within scope; write tests with code
5. Run checks: `ruff`, `black --check`, `mypy`, `pytest`
6. Commit with Conventional Commits format (no task IDs, no co-author trailers)
7. PR with the description template from `SESSION_PROTOCOL.md` §3
8. Merge to `dev` after CI green
9. Update `PROGRESS.md`

---

## Branch Strategy

| Branch | Target |
|---|---|
| `feature/*` | tests + lint only |
| `dev` | GCP development environment |
| `stage` | Azure staging environment |
| `main` | AWS production environment |
| `hotfix/*` | fast-track to production |

---

## Status

In active development. Current phase visible in `PROGRESS.md` at the topmost `[ ]` task.

---

## License

MIT — see [`LICENSE`](LICENSE).
