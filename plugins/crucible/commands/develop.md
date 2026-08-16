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

**Phases:** 0 → 1 → 2 → 2.5 → 3 → 4 → 5 → 6 → 6.5

### LIGHT workflow
Everything else: infrastructure, CLI cosmetics, docs, tests, config, reporting, refactoring non-critical code.

**Phases:** 0 → 2.5 → 3 → 4 → 5 → 6 → 6.5 (skips Research and Architecture)

### TRIVIAL
Typos, 1-line fixes, formatting, comment updates.

**No ceremony.** Just do it, verify, done. No isolate/integrate (Phases 2.5/6.5 skipped).

---

## 2. PHASE 0 — CLASSIFY & ALIGN (all workflows)

1. State the classification: `FULL`, `LIGHT`, or `TRIVIAL`.
2. State the **target repo(s)/scope**.
3. State alignment — how does this advance the project's goals? If it advances nothing obvious, justify it (tech debt, correctness, prerequisite).
4. Create a task list with all phases (TaskCreate) — keep it visible throughout.
5. Record the starting test count by running the repo's test command (e.g. `<your test runner --collect-only>`) — a live snapshot at the branch point. The QA gate re-derives this baseline from ground truth (the branch-point commit), so it's the clean branch point that matters, not a memorized number.

**Gate:** user confirms classification and alignment before proceeding.

---

## 3. PHASE 1 — RESEARCH (FULL only)

Understand the code and gather external best practices before designing.

**Start with the routing table, not with candidate files.** Searching a repo's docs by
opening likely-looking ones costs the full text of everything you opened and were wrong
about, so the price of orienting scales with the size of the corpus rather than the size of
the answer:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/cms/scripts/triage.py" --repo .
```

It prints path, status and summary for every document that has one — read that, pick the
one or two worth opening, and open those. Documents with no summary are listed too, so the
table cannot quietly route you around the part of the corpus it cannot see.

Then launch in parallel (single message, multiple Agent calls):

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

### Record the prediction (FULL only)

Once the plan is approved and before implementing, write down what this change is expected
to do and what would settle it:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/predictions.py" record <branch-slug> \
  --claim "<what this change should achieve, in falsifiable terms>" \
  --check "<the command or observation that would settle it>" \
  --date <YYYY-MM-DD>
```

Every change in a repo was justified at the time. What a repo never accumulates is evidence
about whether the justifications were *right*, because the prediction is made here and the
outcome arrives weeks later somewhere else, and nothing puts the two side by side. The
result is a codebase where every decision looked sound and the overall direction cannot be
evaluated. Thirty seconds now is the whole cost of fixing that.

Make it falsifiable or do not write it. "This will improve quality" cannot be wrong and so
is graded correct in hindsight, every time. "The hook will block frontmatter errors that CI
would otherwise catch a day later, and I expect at least one in the next ten skill edits"
can be wrong, which is the only reason to record it. The script refuses a prediction with
no `--check` for exactly this reason.

---

## 4.5 PHASE 2.5 — ISOLATE (FULL + LIGHT; TRIVIAL skips)

Put the work in its own workspace before touching code, so changes never land
uncommitted on a shared or deploy branch.

Invoke the `start-branch` skill. It detects the repo's integration target (never
hardcoded) and **records it on the branch** in git config, so the INTEGRATE phase and the
QA gate recover that answer instead of re-deriving it — a re-run of the heuristic can pick
a different target than the one this work forked from, and would discard the user's
correction in the ambiguous case that made them correct it. It also auto-chooses a plain
branch vs. a worktree, names the branch in Conventional Branch form, records a clean test
baseline, and proposes a one-line plan you confirm before anything is created.

- **On confirm:** implement (Phase 3) in the isolated branch/worktree.
- **On decline:** continue in place — no branch. Integration (Phase 6.5) then has nothing
  to finish.

Keep all branch logic in the skill; this phase only invokes it.

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

### 4.0 Run the deterministic checks FIRST — yourself, before delegating

Anything a script can decide, a script decides. Run these in the main loop and carry the
**results** into the review; do not ask a subagent to remember to run them.

**First, find out what this project supports** — the right gates differ per project, and a
repo may hold several independent ones:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/detect_profile.py" --emit-gates   # + --repo/--max-depth
```

`0` = one runnable command per line on stdout, already scoped to the right directory ·
`2` = **could not determine** · `3` = **nothing runnable — a SKIP, not a pass.**

**Run every line it prints**, and treat a non-zero exit from any of them as a QA failure.
Drop `--emit-gates` for the human-readable report, or add `--json` for the full structure.

Anything the detector calls a *capability* — a browser suite whose config starts no server,
say — is deliberately **not** printed as runnable; it goes to stderr instead. Running one
against nothing collects zero tests and exits clean, and zero tests passing is not a pass.
That is why the split exists in the tool rather than in your judgement.

Then run the coverage check for each Python root it reported:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/coverage_delta.py"   # + --repo/--target/--base/--collect-cmd as needed
```

`0` = no test disappeared · `1` = **coverage regression** — tests present at the branch point
are gone; this is a REJECT unless each removal has a stated reason (behaviour deliberately
deleted, or the test moved and appears under ADDED) · `2` = **could not determine, which is
not a pass** — fix the invocation (usually `--collect-cmd`) and re-run.

Then run the repo's standing constraints, if it has any:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/invariants_run.py"   # + --repo/--file
```

`0` = every wired check passed · `1` = **an invariant was violated** — a constraint agreed to
hold for all work here no longer does · `2` = could not determine · `3` = **nothing
enforceable** (no file, or no entry has a check yet) — a SKIP, not a pass.

This exists because a constraint stated once is least salient exactly when it is about to be
broken, and restating it does not help: the thing doing the forgetting is the thing being
asked to remember. A script does not care how long ago the rule was written.

Profile catalogue and the deliberate non-goals:
[references/evidence-profiles.md](references/evidence-profiles.md).

Why this sits here and not in the gatekeeper's instructions: it was measured. Asking the
agent to compare test sets by eye caught a green-but-shrunken suite 3 times in 6; giving it
this script and asking it to run the script caught it 2 times in 6. The check was never the
weak part — the *request* was. A step the workflow executes runs every time; a step an agent
is told to perform runs sometimes. Put deterministic checks on this side of that line.

State the exit code in the QA record, and hand it to the gatekeeper as an input rather than
an assignment.

### 4.1 Then review

Use a `qa-gatekeeper` agent if your project provides one; otherwise do QA directly. Give it
the Phase 4.0 results. Checks (all projects):

1. All tests pass.
2. No passing-test regression vs. the branch-point baseline (derived live, not a stated number) — fewer passing tests or a newly failing test is a regression; *more* tests (the milestone added them) is not.
3. No coverage regression — from the Phase 4.0 exit code, not from judgement. Counts cannot see this: delete one test and add another and the count is unchanged, and the suite stays green precisely because what would have failed is no longer asked.
4. No orphaned code (stale references to renamed/deleted symbols) — and no *unreached* code: a control that is constructed but never called is not orphaned, it just does nothing.
5. Lint clean (your linter).
6. No security issues (no hardcoded secrets, no injection).
7. Conventions followed (see the repo's CLAUDE.md).
8. Performance check — no new serial loop over independent expensive work where parallelism is feasible.

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

1. Verify the final suite is green with no passing-test regression vs. the branch-point baseline (more tests than baseline is expected, not a regression).
2. Version bump (FULL only): patch by default; minor for a designated major feature. LIGHT: skip unless notable.
3. Capture lessons learned: a short note of what worked, what didn't, what was surprising. Persist to memory and/or docs if it's a notable milestone or a critical mistake; otherwise keep it to the conversation.

   **Then settle any prediction that is now answerable** (FULL only):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/predictions.py" list          # what is still open
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/predictions.py" verify <id> \
     --verdict right|wrong|partial|unclear --evidence "<what the check showed>" --date <YYYY-MM-DD>
   ```

   Most predictions are not answerable at merge time — leave those open; the weekly
   `curate` pass picks them up. Verify the ones whose check has already run, and **verify
   them honestly**: the ledger's entire value is in its `wrong` entries, `list` says so
   out loud when it has never recorded one, and the recorded claim cannot be edited to
   match the outcome.
4. Mark all tasks complete (TaskUpdate).
5. Summary to the user: what was done, version bump, test count, open items.
6. Debrief (FULL only), in plain language — **Findings** (what the results actually showed, with numbers), **Lessons learned**, **Recommendations**, **Path forward** (next 1–3 priorities).

---

## 8.5 PHASE 6.5 — INTEGRATE (FULL + LIGHT; TRIVIAL skips)

Close out the isolated work. Skip if Phase 2.5 was declined (nothing was isolated) or for
TRIVIAL tasks.

Invoke the `finish-branch` skill. It gates on tests (no green, no merge), presents
**merge / open PR / keep / discard**, defaults to a PR for deploy/protected targets (never
pushing to them by surprise), and cleans up without losing unmerged work (`-d` for merged
branches; `-D`/`--force` only via the informed-discard path; prompt on dirty/unmerged).

Run this after Phase 6's version bump so the bump commit is part of what integrates.

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
| 2.5 — Isolate | `start-branch` skill | Before Implement | FULL + LIGHT (TRIVIAL skips) |
| 3 — Implement | Direct or concurrent teams | When independent | All |
| 4.0 — Deterministic checks | none (you run them) | Before delegating | All |
| 4.1 — QA | qa-gatekeeper or direct | After each milestone | All |
| 5 — Docs | Direct (via `cms`) | After QA pass | All |
| 6 — Completion | Direct | After all milestones | All |
| 6.5 — Integrate | `finish-branch` skill | After Completion | FULL + LIGHT (TRIVIAL skips) |

## CHECKLIST (every task)

Before: target identified · classified · alignment stated · task list visible · starting test count recorded · work isolated via `start-branch` (FULL/LIGHT; target auto-detected + confirmed) — or isolation explicitly declined.
During: deterministic checks run by you (coverage delta) before each review · QA after each milestone · docs updated after each QA pass · task list current.
After: final test count verified · version bumped (per tier) · lessons captured · tasks complete · branch integrated via `finish-branch` (merge/PR/keep/discard + safe cleanup, FULL/LIGHT) · debrief delivered (FULL only).
