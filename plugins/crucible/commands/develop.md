---
description: "Structured development workflow — task classification, research, architecture, implementation with QA gates, and documentation updates. Use for implementation work in a target repo. Do NOT use for pure research/analysis or one-shot data exploration."
allowed-tools: ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Agent", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet"]
---

# Ways of Working (WoW) — Development Workflow

Every task is **classified**, then follows its tier: ceremony where a subtle bug is
expensive, none where it is not. `<...>` parts are the project's to fill in. The reasons
behind each rule: [references/develop-rationale.md](references/develop-rationale.md).

## FIRST — show the plan, before any other tool call

Decide the tier (§1) from the task alone, then make `TaskCreate` your **first tool call**:
one task per phase of that tier — FULL 0 · 1 · 2 · 2.5 · 3 · 4 · 5 · 6 · 6.5, LIGHT 0 · 2.5 ·
3 · 4 · 5 · 6 · 6.5, TRIVIAL none. Every title ends with an estimate and the first also with
the total: `Phase 0: Classify & align (~5 min) — total ~90 min`. The user watches this list
to see progress and time left.

Keep it current with `TaskUpdate`: **in_progress** when a phase starts, **completed** when its
gate passes; add one task per milestone once the plan is set; when a milestone overruns, change
its estimate and the total in the titles. If the task tools are not among your tools (or a
call fails), print the same list as a plain checklist in your first message and re-print it
with ticks at each gate — never skip it silently. If the user changes the tier, add or delete
tasks to match.

## 0. SCOPE

Find the target from the paths in the task, then the working directory; ask if ambiguous.
Several repos/packages → **CROSS-CUTTING** at the end.

## 1. CLASSIFY

- **FULL** — the change touches **critical logic**: core domain logic, public APIs/schemas/data
  contracts (column names, wire formats, table names), anything other code depends on, auth,
  payments, migrations. Phases 0 → 1 → 2 → 2.5 → 3 → 4 → 5 → 6 → 6.5.
- **LIGHT** — everything else (infra, CLI, docs, tests, config, non-critical refactors).
  Phases 0 → 2.5 → 3 → 4 → 5 → 6 → 6.5 (no research, no architecture).
- **TRIVIAL** — typos, 1-line fixes, formatting, comments. **No ceremony.** Just do it,
  verify, done. No isolate/integrate (Phases 2.5/6.5 skipped).
- **ULTRA** — **never your choice**: only when the user's own words ask for it. FULL, plus
  the long-run controls in **ULTRA** below.

## 2. PHASE 0 — CLASSIFY & ALIGN (all)

State the tier, the target repo(s)/scope, and how this advances the project's goals (or why
it is worth doing anyway). Record the starting test count (`<your test runner --collect-only>`) — a snapshot;
the gates re-derive the branch point themselves.

**Gate:** user confirms classification and alignment before proceeding.

## 3. PHASE 1 — RESEARCH (FULL only)

Start with the docs routing table, not candidate files ([why](references/develop-rationale.md#phase-1--start-with-the-routing-table)):
`python3 "${CLAUDE_PLUGIN_ROOT}/skills/cms/scripts/triage.py" --repo .` — open only the one
or two documents worth opening. Then launch in parallel (one message, several Agent calls):
**Explore** (1 for focused work, 2–3 for broad) to trace the affected code and reusable
patterns, and **one web-research** agent (`general-purpose`) for best practice, pitfalls,
prior art. **Ask every agent for a report of at most ~600 words: facts with `file:line`
and sources, no recommendations unless asked** — long reports cost context and bury the
finding.

**Output:** patterns to reuse (paths), external practice that applies, pitfalls, the design
decisions to make.

## 4. PHASE 2 — ARCHITECTURE & PLAN (FULL only)

Run a `Plan` agent on the Phase 1 output, the alignment and the user's constraints, asking
for at most ~1,200 words: ordered milestones, files to create/modify, existing utilities to
reuse — and for anything new, why existing code could not serve — test strategy, risks. If
the change touches prompts, skills, agent instructions or other model output, the
prediction's check is an eval: invoke `eval-first` and freeze its baseline first.

**Gate:** present the plan to the user for approval. Do NOT implement without explicit approval.

**Fix budget (FULL + LIGHT).** At approval — FULL here, LIGHT at the Phase 0 confirmation —
open the ledger with the user's words and an estimate per milestone:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/milestone_ledger.py" init --tier FULL \
  --estimate M1=<minutes> --estimate M2=<minutes> --user-said "<the user's approval, verbatim>"
```

Each milestone gets 3 fix rounds (every REJECT counts), 3 setup rounds for environment
failures, and twice its estimate; only the user changes these ([why](references/develop-rationale.md#phase-2--why-a-fix-budget)).

**Prediction (FULL).** Run the check against the tree as it stands, then record what it showed:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/predictions.py" record <branch-slug> --claim "<falsifiable>" \
  --check "<what would settle it>" --baseline "<what it shows NOW>" --date <YYYY-MM-DD>
```

A check you have never watched fail is not a check: if it already passes on the unchanged
tree, write a different one ([why](references/develop-rationale.md#phase-2--why-record-a-prediction)).

**ULTRA** (a long run with few interruptions). At plan approval the user also names where
the run must stop; init with `--tier ULTRA --checkpoint M<n> [--criteria <acceptance.json>]`
and their words (the script refuses ULTRA unless those words say so). Then: each milestone's
research may fan out to up to 4 **read-only** agents (within the cap; all writing stays
single-threaded) · every QA round uses `qa_gates.py --final` · between checkpoints **carry
on without asking** — log each choice you make alone with `milestone_ledger.py decide M<n>
--note` · at `STOP CHECKPOINT-PREREGISTERED`, stop and ask, then `clear M<n> --user-said` ·
the acceptance criteria are frozen: flip `pass`, never rewrite one (ship/PASS refuse if you
did). Fix-budget checkpoints, integration and release stay the user's call.

## 4.5 PHASE 2.5 — ISOLATE (FULL + LIGHT)

Invoke `start-branch`: it detects the integration target, **records it on the branch** in
git config ([why](references/develop-rationale.md#phase-25--why-the-integration-target-is-recorded)),
picks branch vs. worktree, names it, records a test baseline, and confirms a one-line plan.
On decline, continue in place (6.5 then has nothing to finish). Branch logic stays in the skill.

## 5. PHASE 3 — IMPLEMENT (all)

1. Break the work into 2–5 milestones; do one at a time, opening each with
   `milestone_ledger.py start M<n>`.
2. **FULL: each milestone opens with its own narrow research** — one lookup on the APIs,
   libraries and prior art it touches — in parallel with its first build step, never only
   after a failure. Record it: `milestone_ledger.py research M<n> --note "<what it changed>"`;
   a PASS cannot close a FULL milestone without it.
3. After each milestone → **Phase 4** immediately. Never batch milestones before QA.
   Mark each milestone's task in_progress when you start it and completed when it passes.

Parallelize independent work (different modules, no shared state); serialize when files
share structures or order matters. At most **5** agents at once (research included) unless
the user sets another cap. No serial loops over independent expensive work where the
runtime offers parallelism — flag one in QA.

## 6. PHASE 4 — QA (after each milestone)

### 4.0 Deterministic checks — yourself, in one call

Anything a script can decide, a script decides, and each gate runs once
([why](references/develop-rationale.md#phase-40--why-the-checks-are-scripts-run-by-you)):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/qa_gates.py"           # every QA round
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/qa_gates.py" --final   # a milestone's last round: also plants defects
```

It runs what `detect_profile.py` finds (tests, coverage delta, duplicate-code and lint
deltas), the revert probe and the invariants — read-only gates concurrently, test gates one
at a time unless `.crucible/qa.json` declares them parallel-safe — prints a line per gate,
each failing gate's tail and `QA-GATES: PASS|FAIL|UNDETERMINED|SKIP`, and stores the verdict
for this exact tree. `0` pass · `1` a gate failed · `2` **could not determine, not a pass** ·
`3` nothing to gate (a SKIP). A gate's `1` means:

| Gate | `1` = |
|---|---|
| tests | something that passed at the branch point fails now |
| coverage-delta | tests present at the branch point are gone — REJECT unless each removal has a stated reason |
| clones, lint-delta | findings new since the branch point — each needs a stated reason or a fix, else REJECT |
| revert-probe | the changed tests pass without the change — REJECT unless deliberately test-neutral |
| mutation-probe | planted defects survived — each is a finding: kill it with a test, or show it equivalent |
| invariants | a standing constraint no longer holds |

Catalogue: [references/evidence-profiles.md](references/evidence-profiles.md).

### 4.1 Review

Use the `qa-gatekeeper` agent if the project has one, else review directly. Hand it the
`QA-GATES` line — it reads the stored verdict (`qa_gates.py --show`), it does not re-run
anything. **Re-check what any agent reports before passing it on:** re-run the command
behind each verdict-bearing claim (a result, a count, "no other occurrence"). Beyond the
gates: no orphaned or *unreached* code · no secrets or injection · the repo's conventions ·
no new serial loop over independent expensive work · **claim provenance** — no number or
behavioural claim from outside this session written into a test, constant or docstring as
fact until derived here · **every occurrence** — a fix covers each instance of the defect's
shape, worst case shown (gatekeeper §4e).

**Verdicts go through the ledger.** Record each — `milestone_ledger.py record M<n> --verdict
PASS|CONDITIONAL_PASS|REJECT --kind <failing gate>` (`setup` if the environment failed) — run
`status M<n>` before any further fix, and follow the first line printed:

- `PROCEED` → after a REJECT, fix and re-run QA; after a pass, docs, then the next milestone.
- `STOP DIAGNOSE` → the same gate failed twice: find the mechanism (not a third variation), then `diagnose M<n> --note`.
- `STOP CHECKPOINT-*` → stop fixing. Ask the user: **ship** the best result, **continue**, or **restart** from the plan; record it with `ship|extend|restart M<n> --user-said "<their words>"`. Never choose for them.
- `STOP CHECKPOINT-PREREGISTERED` (ULTRA) → a stop the user set in advance: ask them, then `clear M<n> --user-said`.
- `STOP RESEARCH-MISSING` → record the milestone's research. Exit `2` → could not determine, not a pass.

After each verdict give the user one status line (`report`) and carry on — a progress
report, not a question.

## 7. PHASE 5 — DOCS (after each QA pass)

Update only what changed, through the `cms` skill for any `.md` edit: the repo's CLAUDE.md
for new commands, modules, paths, conventions or version bumps; shared docs when a
cross-repo rule or contract changed; test counts and versions when they changed.

## 8. PHASE 6 — COMPLETION

1. Final suite green, no regression against the branch point (more tests is expected).
2. Version bump (FULL): patch by default, minor for a designated feature; LIGHT only if notable.
3. Lessons learned — persisted for a notable milestone or a critical mistake.
4. Settle any answerable prediction (FULL), **honestly** — the ledger's value is its `wrong`
   entries; leave the rest open for `curate`:
   `predictions.py list` · `predictions.py verify <id> --verdict right|wrong|partial|unclear --evidence "<what the check showed>" --date <YYYY-MM-DD>`
5. Every task completed (`TaskUpdate`), with the actual time against the estimate; summary (what was done, version, test count, open items); for FULL a
   debrief — **Findings** with numbers, **Lessons**, **Recommendations**, **Path forward**.

## 8.5 PHASE 6.5 — INTEGRATE (FULL + LIGHT)

After the version bump, invoke `finish-branch`: no green, no merge; it offers **merge /
open PR / keep / discard**, recommends a PR where the target is protected or runs CI, and
cleans up without losing unmerged work. Skip if nothing was isolated.

## CROSS-CUTTING

Find every affected repo; classify at the **highest** tier among them; implement upstream
producers before downstream consumers; QA each repo before the next; re-verify downstream.

## CHECKLIST

Before: task list shown first · target · tier · alignment · starting test count · isolated (or declined).
During: milestone research (FULL) · `qa_gates.py` before each review · every verdict in the
ledger, checkpoints taken to the user · docs after each pass.
After: final suite · version · lessons · predictions settled · integrated · debrief (FULL).
