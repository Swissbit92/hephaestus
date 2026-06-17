---
description: "Structured development workflow — task classification, research, architecture, implementation with QA gates, and documentation updates. Use for implementation work in a target repo. Do NOT use for pure research/analysis or one-shot data exploration."
allowed-tools: ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Agent"]
---

# Ways of Working (WoW) — Development Workflow

A disciplined workflow for implementation work. Every task is **classified**, then follows the matching tier. The point is to spend ceremony where it pays off (critical logic) and skip it where it doesn't (typos, cosmetics).

> Adapt the per-repo specifics (critical paths, test commands, alignment questions) to your project. The structure below is repo-agnostic; the bracketed `<...>` parts are yours to fill in.

---

## 0. REPO / SCOPE DETECTION

Determine what the task targets:

1. Check file paths mentioned in the task.
2. Check the current working directory.
3. If ambiguous, ask the user.

If the task spans multiple repos/packages → see **CROSS-CUTTING TASKS** at the end.

---

## 1. TASK CLASSIFICATION

Classify before writing any code.

### FULL workflow
Triggers when the task modifies **critical logic** — the parts where a subtle bug is expensive or hard to detect. Define these for your project, e.g.:

- Core domain logic / algorithms
- Public APIs, schemas, data contracts (column names, wire formats, collection/table names)
- Anything other code or repos depend on
- Auth, payments, migrations, anything with a blast radius

**Phases:** 0 → 1 → 2 → 3 → 4 → 5 → 6

### LIGHT workflow
Everything else: infrastructure, CLI cosmetics, docs, tests, config, reporting, refactoring non-critical code.

**Phases:** 0 → 3 → 4 → 5 → 6 (skips Research and Architecture)

### TRIVIAL
Typos, 1-line fixes, formatting, comment updates.

**No ceremony.** Just do it, verify, done.

---

## 2. PHASE 0 — CLASSIFY & ALIGN (all workflows)

1. State the classification: `FULL`, `LIGHT`, or `TRIVIAL`.
2. State the **target repo(s)/scope**.
3. State alignment — how does this advance the project's goals? If it advances nothing obvious, justify it (tech debt, correctness, prerequisite).
4. Create a task list with all phases (TaskCreate) — keep it visible throughout.
5. Record the starting test count: run the repo's test command (e.g. `<your test runner --collect-only>`).

**Gate:** user confirms classification and alignment before proceeding.

---

## 3. PHASE 1 — RESEARCH (FULL only)

Understand the code and gather external best practices before designing.

Launch in parallel (single message, multiple Agent calls):

| Agent | Type | Purpose |
|-------|------|---------|
| Explore (1–3) | `Explore` | Understand affected areas, trace execution paths, find reusable patterns |
| Web research (1) | `general-purpose` | Best practices, known pitfalls, prior art for this kind of change |

Use 1 Explore agent for focused changes, 2–3 for broad/uncertain scope.

**Output before Phase 2:** patterns to reuse (with file paths), external best practices that apply, pitfalls to avoid, key design decisions to make.

---

## 4. PHASE 2 — ARCHITECTURE & PLAN (FULL only)

Design the blueprint, informed by Phase 1.

Run a `Plan` agent. Feed it: Phase 1 exploration results, web-research findings, project alignment, and the user's constraints.

It should produce: implementation milestones (ordered), files to create/modify (paths), existing utilities to reuse (paths), test strategy, and risk areas.

**Gate:** present the plan to the user for approval. Do NOT implement without explicit approval.

---

## 5. PHASE 3 — IMPLEMENT (all workflows)

1. Break work into 2–5 logical milestones.
2. Implement one milestone at a time.
3. After each milestone → immediately run **Phase 4 (QA)**.
4. Do NOT batch multiple milestones before QA.
5. Keep the task list current (TaskUpdate).

### Concurrent agent teams (within a milestone)
Parallelize when work is independent (different modules, no shared imports; tests vs. implementation in different files). Serialize when files share data structures, changes cascade, or order matters for correctness. Judgment call per task.

### Performance discipline
Don't write serial loops over independent, expensive units of work when the language/runtime offers real parallelism — use it (process pools, workers, batching), and send shared data to workers once rather than per task. A serial loop over independent CPU-bound work is a code smell — flag it in QA.

---

## 6. PHASE 4 — QA GATEKEEPER (after each milestone)

Catch issues before they compound.

Use a `qa-gatekeeper` agent if your project provides one; otherwise do QA directly. Checks (all projects):

1. All tests pass.
2. No test-count regression vs. the Phase 0 baseline.
3. No orphaned code (stale references to renamed/deleted symbols).
4. Lint clean (your linter).
5. No security issues (no hardcoded secrets, no injection).
6. Conventions followed (see the repo's CLAUDE.md).
7. Performance check — no new serial loop over independent expensive work where parallelism is feasible.

**Verdicts:** PASS → proceed to docs, then next milestone. CONDITIONAL PASS → fix minor issues, proceed. REJECT → fix critical issues, re-run QA; do not proceed until PASS.

Record the test count after each pass.

---

## 7. PHASE 5 — DOCUMENTATION (after each QA pass)

Keep docs current incrementally — update only what changed. Invoke the `cms` skill for any `.md` edits.

Update the repo's **CLAUDE.md** if: new commands/flags, architecture changes (new modules, renamed paths, new patterns), new/changed test modules, version bumps, or new/changed conventions.

Update **root/shared docs** if cross-repo rules or shared contracts changed.

Rules: incremental only; bump test counts if changed materially; bump version numbers if a version bump occurred.

---

## 8. PHASE 6 — COMPLETION (after all milestones)

1. Verify the final test count — confirm no regression vs. Phase 0.
2. Version bump (FULL only): patch by default; minor for a designated major feature. LIGHT: skip unless notable.
3. Capture lessons learned: a short note of what worked, what didn't, what was surprising. Persist to memory and/or docs if it's a notable milestone or a critical mistake; otherwise keep it to the conversation.
4. Mark all tasks complete (TaskUpdate).
5. Summary to the user: what was done, version bump, test count, open items.
6. Debrief (FULL only), in plain language — **Findings** (what the results actually showed, with numbers), **Lessons learned**, **Recommendations**, **Path forward** (next 1–3 priorities).

---

## CROSS-CUTTING TASKS

When a task spans multiple repos/packages:

1. Identify ALL affected repos and the changes each needs.
2. Classify at the **highest** tier across all of them.
3. Implement in **dependency order** (upstream producers before downstream consumers).
4. QA after each repo's changes — don't batch across repos.
5. Verify downstream still works after upstream changes.

---

## QUICK REFERENCE

| Phase | Agents | Parallel? | When |
|-------|--------|-----------|------|
| 1 — Research | Explore (1–3) + web research (1) | Yes | FULL only |
| 2 — Architecture | Plan (1) | After Phase 1 | FULL only |
| 3 — Implement | Direct or concurrent teams | When independent | All |
| 4 — QA | qa-gatekeeper or direct | After each milestone | All |
| 5 — Docs | Direct (via `cms`) | After QA pass | All |
| 6 — Completion | Direct | After all milestones | All |

## CHECKLIST (every task)

Before: target identified · classified · alignment stated · task list visible · starting test count recorded.
During: QA after each milestone · docs updated after each QA pass · task list current.
After: final test count verified · version bumped (per tier) · lessons captured · tasks complete · debrief delivered (FULL only).
