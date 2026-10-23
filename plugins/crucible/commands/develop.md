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
5. Record the starting test count (e.g. `<your test runner --collect-only>`) — a live snapshot at the branch point; the QA gate re-derives it from the branch-point commit, not a memorized number.

**Gate:** user confirms classification and alignment before proceeding.

---

## 3. PHASE 1 — RESEARCH (FULL only)

Understand the code and gather external best practices before designing.

**Start with the routing table, not with candidate files** ([why](references/develop-rationale.md#phase-1--start-with-the-routing-table)):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/cms/scripts/triage.py" --repo .
```

Read it, pick the one or two documents worth opening, and open those.

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

It should produce: implementation milestones (ordered), files to create/modify (paths), existing utilities to reuse (paths) — and for anything new, why existing code could not serve — test strategy, and risk areas.

If the change touches prompts, skills, agent instructions or anything else whose output a
model produces, the prediction's check is an eval: invoke `eval-first` and freeze its
baseline before implementing, with its pre-flight (determinism, interval, sample size).

**Gate:** present the plan to the user for approval. Do NOT implement without explicit approval.

### Set the fix budget (FULL + LIGHT)

At approval — FULL after this gate, LIGHT at the Phase 0 confirmation — open the milestone
ledger with the user's words and an estimate per milestone:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/milestone_ledger.py" init --tier FULL \
  --estimate M1=<minutes> --estimate M2=<minutes> --user-said "<the user's approval, verbatim>"
```

Each milestone gets 3 fix rounds (every REJECT counts, whatever its cause), 3 setup rounds
for environment failures, and twice its estimate. Only the user changes these — at plan
approval, or at a checkpoint ([why](references/develop-rationale.md#phase-2--why-a-fix-budget)).

### Record the prediction (FULL only)

Once the plan is approved and before implementing, write down what this change is expected
to do and what would settle it:

**Run the check first, against the tree as it stands.** Then record what it showed:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/predictions.py" record <branch-slug> \
  --claim "<what this change should achieve, in falsifiable terms>" \
  --check "<the command or observation that would settle it>" \
  --baseline "<what that check shows RIGHT NOW, before the change>" \
  --date <YYYY-MM-DD>
```

Make it falsifiable or do not write it — the script refuses a prediction with no `--check`.
**And run the check before you record it — a check you have never watched fail is not a
check.** If it already passes on the unchanged tree, you do not have a baseline — you have a
different check to write. The evidence behind both rules:
[references/develop-rationale.md](references/develop-rationale.md#phase-2--why-record-a-prediction).

---

## 4.5 PHASE 2.5 — ISOLATE (FULL + LIGHT; TRIVIAL skips)

Put the work in its own workspace before touching code, so changes never land
uncommitted on a shared or deploy branch.

Invoke the `start-branch` skill. It detects the repo's integration target (never
hardcoded) and **records it on the branch** in git config, so later phases and the gate
scripts read it instead of re-guessing ([why](references/develop-rationale.md#phase-25--why-the-integration-target-is-recorded)).
It also chooses a plain branch vs. a worktree, names the branch in Conventional Branch form,
records a clean test baseline, and confirms a one-line plan before anything is created.

- **On confirm:** implement (Phase 3) in the isolated branch/worktree.
- **On decline:** continue in place — no branch. Integration (Phase 6.5) then has nothing
  to finish.

Keep all branch logic in the skill; this phase only invokes it.

---

## 5. PHASE 3 — IMPLEMENT (all workflows)

1. Break work into 2–5 logical milestones.
2. Implement one milestone at a time; open each with `milestone_ledger.py start M<n>`.
3. **FULL: each milestone opens with its own narrow research** — the APIs, libraries and
   prior art it touches — in parallel with its first build step, never only after a failure.
   Record it: `milestone_ledger.py research M<n> --note "<what it changed>"`; a PASS cannot
   close a FULL milestone without it.
4. After each milestone → immediately run **Phase 4 (QA)**. Do NOT batch milestones before QA.
5. Keep the task list current (TaskUpdate).

### Concurrent agent teams (within a milestone)
Parallelize when work is independent (different modules, no shared imports; tests vs. implementation in different files). Serialize when files share data structures, changes cascade, or order matters for correctness. Judgment call per task. At most **5** agents at once (milestone research included) unless the user sets another cap — detail is lost in every hand-off.

### Performance discipline
No serial loops over independent, expensive work where the runtime offers parallelism (pools, workers, batching); send shared data once, not per task. Flag one in QA.

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

Two printed lines are delta gates — `metric_delta.py --metric clones` (duplicated code) and
`--metric ruff` (where configured) — reporting only findings new since the branch point:
`1` = **new findings**, each needing a stated reason or a fix, otherwise REJECT · `2` =
could not determine · `3` = nothing to measure (a SKIP).

Anything the detector calls a *capability* (a browser suite whose config starts no server)
is deliberately **not** printed as runnable; it goes to stderr.

Then run the coverage check for each Python root it reported:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/coverage_delta.py"   # + --repo/--target/--base/--collect-cmd as needed
```

`0` = no test disappeared · `1` = **coverage regression** — REJECT unless each removal has a
stated reason (behaviour deliberately deleted, or the test moved and appears under ADDED) ·
`2` = **could not determine, not a pass** — fix the invocation (usually `--collect-cmd`).

For Python changes, check that the tests depend on the change — every milestone `--revert`
(the branch point's code restored in a throwaway copy), the final milestone also `--mutate`
(up to 6 planted defects in the changed functions):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/mutation_probe.py" --revert   # | --mutate
```

`0` = the tests depend on the change / every mutant killed · `1` = **they pass without it**
(REJECT unless deliberately test-neutral) / **mutants survived** (each a finding) · `2` =
could not determine (a canary failed) · `3` = nothing to probe (a SKIP).

Then run the repo's standing constraints, if it has any:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/invariants_run.py"   # + --repo/--file
```

`0` = every wired check passed · `1` = **an invariant was violated** — a constraint agreed to
hold for all work here no longer does · `2` = could not determine · `3` = **nothing
enforceable** (no file, or no entry has a check yet) — a SKIP, not a pass.

Profile catalogue and the deliberate non-goals:
[references/evidence-profiles.md](references/evidence-profiles.md).

Why these are scripts you run rather than instructions the gatekeeper follows — a measured
3/6 vs 3/3 — and why the delta gates compare sets, not counts:
[references/develop-rationale.md](references/develop-rationale.md#phase-40--why-the-checks-are-scripts-run-by-you).

State the exit code in the QA record, and hand it to the gatekeeper as an input rather than
an assignment.

### 4.1 Then review

Use a `qa-gatekeeper` agent if your project provides one; otherwise do QA directly. Give it
the Phase 4.0 results. **Re-check what any agent reports before passing it on:** a verdict
is evidence to verify, not a conclusion — re-run the command behind each verdict-bearing
claim (a result, a count, "no other occurrence") before it reaches the user or the ledger.
Checks (all projects):

1. All tests pass.
2. No passing-test regression vs. the branch-point baseline (derived live, not a stated number) — fewer passing tests or a newly failing test is a regression; *more* tests (the milestone added them) is not.
3. No coverage regression — from the Phase 4.0 exit code, not from judgement: delete one test and add another and the count is unchanged while the suite stays green.
4. No orphaned code (stale references to renamed/deleted symbols) — and no *unreached* code: a control that is constructed but never called is not orphaned, it just does nothing.
5. Lint clean (your linter).
6. No security issues (no hardcoded secrets, no injection).
7. Conventions followed (see the repo's CLAUDE.md).
8. Performance check — no new serial loop over independent expensive work where parallelism is feasible.
9. Claim provenance — no number, benchmark or behavioural claim that arrived from *outside this session* (another agent, another session, a person, a doc) is written into a test, a constant or a docstring as fact until derived here, from the source. A pinned wrong value acquires a guard.
10. Every occurrence — a fix covers every instance of the defect's shape across the repo, worst case shown, not only the reported one (gatekeeper §4e).

**Verdicts go through the ledger.** Record each — `milestone_ledger.py record M<n> --verdict
PASS|CONDITIONAL_PASS|REJECT --kind <failing gate>` (`setup` if the environment failed) — run
`status M<n>` before any further fix, and follow the first line printed:

- `PROCEED` → after a REJECT, fix and re-run QA; after a pass, docs, then the next milestone.
- `STOP DIAGNOSE` → the same gate failed twice: find the mechanism (not a third variation), then `diagnose M<n> --note`.
- `STOP CHECKPOINT-*` → stop fixing. Ask the user: **ship** the best result, **continue**, or **restart** from the plan; record it with `ship|extend|restart M<n> --user-said "<their words>"`. Never choose for them.
- `STOP RESEARCH-MISSING` → record the milestone's research. Exit `2` → could not determine, not a pass.

After each verdict give the user one status line (`report`) and carry on — a progress report,
not a question. Record the test count after each pass.

---

## 7. PHASE 5 — DOCUMENTATION (after each QA pass)

Keep docs current incrementally — update only what changed. Invoke the `cms` skill for any `.md` edits.

Update the repo's **CLAUDE.md** if: new commands/flags, architecture changes (new modules, renamed paths, new patterns), new/changed test modules, version bumps, or new/changed conventions.

Update **root/shared docs** if cross-repo rules or shared contracts changed.

Rules: incremental only; bump test counts and version numbers when they changed.

---

## 8. PHASE 6 — COMPLETION (after all milestones)

1. Verify the final suite is green with no passing-test regression vs. the branch-point baseline (more tests than baseline is expected, not a regression).
2. Version bump (FULL only): patch by default; minor for a designated major feature. LIGHT: skip unless notable.
3. Capture lessons learned (what worked, what didn't, what surprised) — persisted to memory/docs for a notable milestone or a critical mistake, else kept in the conversation.

   **Then settle any prediction that is now answerable** (FULL only):

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/predictions.py" list          # what is still open
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/predictions.py" verify <id> \
     --verdict right|wrong|partial|unclear --evidence "<what the check showed>" --date <YYYY-MM-DD>
   ```

   Leave unanswerable ones open (`curate` picks them up); verify the rest **honestly** — the
   ledger's value is its `wrong` entries, and a recorded claim cannot be edited to match.
4. Mark all tasks complete (TaskUpdate).
5. Summary to the user: what was done, version bump, test count, open items.
6. Debrief (FULL only), in plain language — **Findings** (what the results actually showed, with numbers), **Lessons learned**, **Recommendations**, **Path forward** (next 1–3 priorities).

---

## 8.5 PHASE 6.5 — INTEGRATE (FULL + LIGHT; TRIVIAL skips)

Close out the isolated work. Skip if Phase 2.5 was declined (nothing was isolated) or for
TRIVIAL tasks.

Invoke the `finish-branch` skill: no green, no merge; it offers **merge / open PR / keep /
discard**, defaults to a PR for protected targets, and cleans up without losing unmerged work.

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
During: milestone research recorded (FULL) · deterministic checks run by you (gates, coverage, probe) before each review · every verdict recorded in the ledger, checkpoints taken to the user · docs updated after each QA pass · task list current.
After: final test count verified · version bumped (per tier) · lessons captured · tasks complete · branch integrated via `finish-branch` (merge/PR/keep/discard + safe cleanup, FULL/LIGHT) · debrief delivered (FULL only).
