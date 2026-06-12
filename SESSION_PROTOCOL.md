# SESSION_PROTOCOL — Claude Code Session Template

**Purpose:** Standardize every Claude Code session in MAISYS. Copy the template below into Claude Code, fill in the task details, and run.

---

## 1. Before You Start

Before opening Claude Code, do these three things on your laptop or the VM:

```bash
git checkout dev
git pull
git checkout -b feature/<short-task-slug>
```

`<short-task-slug>` is a 2–4 word kebab-case description of the task — for example, `upload-local-to-gcs`, `shared-error-handler`, `drug-lookup-agent`. **Do not** put task IDs (`P1-T07`) or phase numbers in the branch name. The branch is what other humans will see in GitHub — keep it clean.

Open `PROGRESS.md` and find the task. Read its scope and required reading sections in the docs **yourself** before invoking Claude Code. If anything is unclear, stop and resolve it before starting the session.

---

## 2. The Session Prompt Template

Copy this verbatim into Claude Code, replacing `<…>` with the task details.

```
You are working on MAISYS. Read /CLAUDE.md fully before doing anything else.

## This session

Task title: <task title from PROGRESS.md>
Task ID for tracking: <e.g., P1-T17>  (used only in PROGRESS.md update at the end — never in commit messages)
Branch (already checked out): feature/<short-task-slug>

## Required reading

Before writing any code, read in order:
1. <doc reference 1, e.g., /docs/technical-guides/part6.md §7>
2. <doc reference 2>
3. The CLAUDE.md files Claude Code loads automatically for this directory

## Scope — files you may create or modify

ONLY these paths:
- <path 1>
- <path 2>
- (and tests for the above in the relevant tests/ folder)

Everything else in the repo is READ-ONLY for this session. If you find yourself wanting to touch a file outside this list, stop and ask.

## Acceptance criteria

The session is done when:
- [ ] All code in scope is implemented
- [ ] Tests are written in the same session (not deferred)
- [ ] `pytest <relevant test path>` passes
- [ ] `ruff check <changed paths>` is clean
- [ ] `black --check <changed paths>` is clean
- [ ] `mypy <changed paths>` is clean
- [ ] The PR description (see §3 below) is drafted
- [ ] PROGRESS.md is updated locally

## Commit conventions (strict)

- Use Conventional Commits format: `<type>(<scope>): <subject>`
- Types: feat, fix, chore, docs, refactor, test, build, ci, perf
- NO task IDs in commit subject (no "P1-T07", no "Phase 1")
- NO co-authoring trailers ("Co-Authored-By:", "Generated with", etc.)
- NO emoji
- Subject line under 72 characters
- Body (optional) explains why, not what

Examples:
  feat(shared): add error_handler module with custom exception hierarchy
  feat(drug-service): implement drug lookup agent
  fix(auth-service): correct JWT expiry validation
  chore: configure pre-commit hooks
  refactor(chunking): split medical chunker into reusable strategies

## How to operate

- Stay strictly within scope. If a needed change is out of scope, surface it — do not silently expand.
- Ask when uncertain. Do not invent architecture; all decisions are in /docs/technical-guides/.
- Write tests alongside code, not after.
- Run all checks before declaring done.
- When done, draft the PR description per §3 of SESSION_PROTOCOL.md and present it to me for review before opening the PR.

Begin.
```

---

## 3. PR Description Template

After Claude Code declares the session done, it drafts a PR description using this template:

```
## Summary

<1-2 sentences: what changed at a high level>

## Why

<1-2 sentences: why this change was needed — refer to the doc section that motivates it>

## Doc reference

<e.g., /docs/technical-guides/part6.md §7 — Error Handling Pattern>

## Changes

- <bullet: file or module changed>
- <bullet: file or module changed>
- <bullet: tests added>

## Test status

- [x] Unit tests: <pass/fail summary>
- [x] Type check (mypy): <pass>
- [x] Lint (ruff): <pass>
- [x] Format (black): <pass>

## Acceptance criteria

- [x] <criterion 1 from PROGRESS.md>
- [x] <criterion 2>
- [x] <criterion 3>

## Notes

<optional: anything reviewer should pay attention to, follow-up tasks, etc.>
```

Keep PR descriptions tight. No marketing language. No emoji. No "🚀 ready to merge".

---

## 4. After the Session

1. **Review the diff yourself:** `git diff dev...HEAD`. Look for out-of-scope changes, anything you don't understand, anything that contradicts the docs.
2. **Run the full check suite locally:**
   ```bash
   ruff check .
   black --check .
   mypy .
   pytest
   ```
3. **Commit (Claude Code usually does this — verify the message follows §2 conventions):**
   ```bash
   git log -1
   ```
4. **Push the branch:**
   ```bash
   git push -u origin feature/<short-task-slug>
   ```
5. **Open the PR** (web UI or `gh pr create`) with the description Claude Code drafted in §3.
6. **Wait for CI** — if any check fails, kick off a follow-up Claude Code session in the same branch to fix.
7. **Merge to `dev`** after CI is green. Squash merge keeps `dev` history clean.
8. **Update PROGRESS.md** — flip `[ ]` to `[x]`, fill in the squash-merge commit hash. Push directly to `dev`.

---

## 5. When to Stop a Session Mid-Way

Stop and intervene if Claude Code:

- Touches a file outside the declared scope → say: *"That file is out of scope for this task. Revert that change and continue within scope."*
- Invents an architectural decision → say: *"Stop. The pattern for this is in `<doc reference>`. Use that pattern."*
- Skips writing tests → say: *"Write tests for this code before continuing."*
- Defers lint or type errors → say: *"Fix these before continuing — no deferred cleanup."*
- Asks an ambiguous question → read the docs yourself, give a clear answer. If the docs are truly silent, decide and log the clarification in `PROGRESS.md` "Clarifications Log".
- Says "I'll do X in a follow-up" → say: *"Either it's in scope or it's a separate task. Decide and stay strict."*

---

## 6. When Things Go Sideways

- **Stuck for 30+ minutes:** Cancel the session. Re-read the task scope. Restart with tighter constraints, or break the task into smaller pieces and update `PROGRESS.md` accordingly.
- **Test suite reveals a conflict with the docs:** Stop. Surface the conflict in the PR description's Notes section. Tag the doc section. Do not silently change either side.
- **CI fails on something unrelated to the task:** That's a separate issue — open a fix-up task in `PROGRESS.md`. Don't expand the current PR to chase it.
- **You discover a missing dependency on another not-yet-done task:** Stop. The task ordering in `PROGRESS.md` is wrong. Fix the ordering, then restart.

---

## 7. Rolling Back

Every task = one branch = one PR = one squash-merge commit. Rollback is one command:

```bash
git revert <merge-commit-sha>
```

Push the revert directly to `dev`. Then reopen the task in `PROGRESS.md` (`[x]` → `[ ]`) with a brief note in the Clarifications Log.

---

*End of session protocol.*
