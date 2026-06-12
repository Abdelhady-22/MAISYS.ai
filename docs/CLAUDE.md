# docs/ — Frozen Reference Documentation

## Purpose

This folder contains the authoritative technical specifications for MAISYS. These documents represent **all architectural decisions** that have been made. Code implements them; code does not invent them.

## Contents

- `frontend-guide/` — design system, page list, i18n, RTL, component patterns
- `technical-guides/` — six parts covering everything backend:
  - **part1** — overview, architecture, deployment topology
  - **part2** — shared library + shared services (auth, translation, safety, notification, model-router)
  - **part3** — module services (chatbot, drug, symptom, lab, research) with full agent details
  - **part4** — Beta training, knowledge graphs, master implementation checklist, monitoring
  - **part5** — database schemas (Postgres per service, Qdrant collections, Redis keys)
  - **part6** — design patterns (chunking, embedding, agent pattern, error handling, KV cache)

## Rules

1. **Read-only.** Never edit a file in this folder during a regular task.
2. **The single source of architectural truth.** When code disagrees with docs, **stop** — surface the conflict. Don't silently change either side.
3. **Reference, don't duplicate.** Other CLAUDE.md files point to sections here. They do not copy doc content.
4. **Doc changes are their own task.** If a doc genuinely needs updating (because a real requirement changed), it gets its own PR with a clear justification — never bundled with code changes.

## When You Can Edit

A doc edit task gets explicit human approval and a dedicated PR. Reasons that justify a doc edit:

- An external requirement changed (e.g., an API was deprecated)
- A previously-undocumented decision was made and logged in `PROGRESS.md` Clarifications Log
- A clear factual error was found (typo, broken link, wrong version number)

Implementation bugs are never grounds for changing docs.
