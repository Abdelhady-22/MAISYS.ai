# MAISYS — Project Root

## What MAISYS Is

MAISYS is a bilingual (Arabic + English) medical AI **education** platform for students, researchers, and curious adults. It is **not** a diagnostic tool, does not replace clinicians, and explicitly directs users to professionals for medical decisions. All output is evidence-grounded with citations to authoritative sources (Mayo Clinic, MedlinePlus, Drugs.com, DDIMDL, PubMed).

Built on 13 microservices deployed across three clouds (GCP dev / Azure stage / AWS prod). Five user-facing modules: Medical Chatbot, Drug Agent, Symptom Checker, Lab Test Explainer, Research Paper Assistant. RAG-based retrieval with dual embeddings, LangGraph-based agent orchestration, KV cache, and a fine-tuned Beta LLM for symptom triage.

## Ironclad Rules

These are non-negotiable. They apply to every session, every file, every commit.

1. **No data files in this repo.** PDFs, CSVs, JSONLs, Parquet, model weights — none. They live in cloud buckets. `.gitignore` enforces this; pre-commit hook backs it up.
2. **No secrets in this repo.** API keys, tokens, passwords live in cloud Secret Manager / Key Vault / Secrets Manager. `.env.example` shows variable names only.
3. **Every script takes cloud URIs**, never local filesystem paths. The only exception is `data-pipeline/cloud/upload_local_to_gcs.py`, which is the one-time bridge from your laptops to GCS.
4. **No architecture decisions in code.** Architectural choices live in `/docs/technical-guides/`. Code implements them; code does not invent them. When ambiguity is found, ask — do not guess.
5. **No file modification outside the current task's declared scope.** Every Claude Code session reads its scope from `PROGRESS.md` and writes only within it.
6. **No silent doc/code drift.** If implementation reveals a conflict with the docs, stop. Surface it. Never silently change the docs to match the code, or write code that contradicts a doc you didn't fully read.
7. **Medical safety overrides everything else.** Emergency detection is never optional. Pediatric and pregnancy modifiers are never optional. Citation requirements are never optional. No agent generates clinical advice; agents generate educational explanations with sources.

## Working in This Repo

Every change goes through this loop:

1. **Find the next task** in `PROGRESS.md` (look for the first `[ ]` checkbox in the current phase).
2. **Read the task's required doc sections** in `/docs/technical-guides/`.
3. **Read the relevant `CLAUDE.md` files** — they're loaded automatically as you walk the directory tree, but skim them yourself too.
4. **Use `SESSION_PROTOCOL.md`** as your session template — paste it into Claude Code with the task ID filled in.
5. **Stay strictly within the declared scope.** Anything else is a follow-up task.
6. **Write tests in the same session as code.** Not "I'll add tests later."
7. **Run all checks before declaring done:** tests pass, types pass (`mypy`), lint clean (`ruff`), format clean (`black`).
8. **Open a PR with the description template** from `SESSION_PROTOCOL.md`.
9. **Update `PROGRESS.md`** — flip `[ ]` to `[x]`, add the commit hash.

## Where to Find Things

| Topic | Reference |
|---|---|
| Project overview & architecture | `docs/technical-guides/part1.md` |
| Shared library & shared services | `docs/technical-guides/part2.md` |
| Module services (chatbot, drug, symptom, lab, research) | `docs/technical-guides/part3.md` |
| Beta training, knowledge graphs, master checklist | `docs/technical-guides/part4.md` |
| Database schemas (Postgres, Qdrant, Redis) | `docs/technical-guides/part5.md` |
| Design patterns (agent, retrieval, error handling) | `docs/technical-guides/part6.md` |
| Frontend (pages, i18n, RTL, design system) | `docs/frontend-guide/MAISYS_frontend_design_guide.md` |
| Data sources, cloud buckets, upload flows | `DATA_PLAN.md` |
| Repo structure, CLAUDE.md hierarchy, build order | `REPO_PLAN.md` |
| Your (human) role at each task | `YOUR_ROLE.md` |
| Active task tracker | `PROGRESS.md` |
| Claude Code session template | `SESSION_PROTOCOL.md` |

## Commit & PR Conventions

**Commits** use Conventional Commits format. Examples:

```
feat(shared): add error_handler module with custom exception hierarchy
feat(drug-service): implement drug lookup agent
fix(auth-service): correct JWT expiry validation
chore: configure pre-commit hooks for lint and type checks
docs: add CLAUDE.md hierarchy for services layer
refactor(chunking): split medical chunker into reusable strategies
test(drug-service): add integration tests for interaction agent
```

**Never** include:
- "Phase 0", "P1-T07", or any task ID in the commit subject
- "Co-Authored-By:", "Generated with", or any AI attribution
- Emoji
- Lengthy multi-paragraph descriptions in the subject line

PROGRESS.md tracks task IDs internally. Commits stay professional.

**PRs** use the template in `SESSION_PROTOCOL.md` §3. Each PR description includes:
- Summary of what changed
- Why (1–2 sentences)
- Doc section reference
- Test status
- Acceptance criteria checklist

## Standing User Preferences

- **No file changes outside declared task scope without explicit approval.**
- **No architecture decisions** — all decisions live in `/docs/technical-guides/`.
- **Bilingual first-class.** Arabic and English are equal, not Arabic-as-translation.
- **Cloud-only data.** Never read or write data files locally.
- **Versioned artifacts.** Embeddings, models, training data are all under `{name}/v{N}/` paths.
- **Test coverage with code, not after.** No "I'll add tests later" sessions.
- **Ask when uncertain.** Better to pause than guess.

## Tone for Human Communication

Direct, technical, no unnecessary praise. If something is broken, say so plainly. If a decision was wrong, name it. If you're confident, say so; if uncertain, say that too. Avoid "let me know if you have any questions" boilerplate.
