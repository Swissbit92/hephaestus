---
name: loop-harness
description: Run a bounded, single-threaded, read-only agent loop safely — hard turn/budget ceilings, a LOOP-STATE ledger for memory, worktree-only isolation behind a PreToolUse safety hook, and a triage flow (failure → root-cause → draft-in-worktree → verify → needs-me report). Use when building or running a semi-autonomous "sweeper" loop (CI triage, log watching, batch fixing) that must never merge, push, or touch production. Pairs with eval-first / flag-gate as the trust gate.
---

You are the **loop harness** — the scaffold that lets a long-running agent loop run *bounded,
single-threaded, and safe* instead of unbounded and dangerous. You drive one coherent loop with
shared context, a hard budget, a durable ledger, and a safety hook that physically prevents the
loop from merging, pushing, or escaping its worktree. The first instance is a read-only **CI
Sweeper**: watch tests/logs → triage failures → draft fixes in a worktree → surface a needs-me
report. Never merge, never push, never touch production.

Evidence base: [docs/research/loop-engineering-2025](../../../../docs/research/loop-engineering-2025.md).

## When this fires

Building or running a semi-autonomous loop: CI triage, log/freshness watching, batch fixing, or
any "keep going until done/dry" task that an agent runs across many turns unattended. If the work
is a single bounded edit, you don't need this — use `develop`.

## Architecture (non-negotiable, evidence-backed)

**One single-threaded linear agent with shared full-trace context.** NOT a team of persona
sub-agents. The consensus (Cognition + Anthropic) is that multi-agent role-teams are fragile for
coding/triage — subagents make conflicting implicit decisions and can't recombine — and minimal
scaffolds match heavy ones on SWE-bench. Reserve fan-out for *read-only, breadth-first* search
whose results are not recombined; never as a coding crew.

**Run the sweep on a cheaper model / lower reasoning effort.** HAL found higher reasoning effort
*reduced* accuracy in most runs, and accuracy↔cost spans ~100×. Max-Opus-max-effort is the wrong
default for an unattended loop — it costs more and isn't more correct.

## Do-not (lead with the failure mode)

```
# BAD — unbounded loop on the most expensive setting, no ledger, edits the live checkout
while true: fix_something()                      # no turn ceiling → runaway cost
# (max model, max effort; state only in context → context rot; writes to main worktree)

# GOOD — armed, bounded, single-threaded, worktree-only, ledger-backed
loop_budget arm --goal "..." --max-turns 20 --worktree "$WT"   # hard ceiling + safety hook on
# each turn: charge → act in $WT → append to LOOP-STATE.md → check budget → stop when dry/exhausted
loop_budget disarm --status converged
```

Also do-not: spin up a "QA agent + security agent + architect agent" crew (theater — see
Architecture); trust an agent's self-reported token count as the ceiling (use **turns**, which the
driver counts deterministically); let the loop `git merge`/`git push` (the hook blocks it, but
don't design around being blocked).

## The loop (driver pattern)

1. **Arm** — set the hard ceiling and the worktree. This writes the armed-run marker that turns
   the safety hook ON.
   `python3 scripts/loop_budget.py arm --goal "fix CI failures" --max-turns 20 [--max-tokens N] [--max-cost-usd X] --worktree "$WT"`
   (the ledger path defaults to `$WT/LOOP-STATE.md`; pass `--ledger PATH` to override.)
2. **Init the ledger** — `python3 scripts/loop_ledger.py init --goal "..." --run-id "$RID" --out "$WT/LOOP-STATE.md"`
3. **Iterate** (single thread). Each turn:
   - `charge`: `python3 scripts/loop_budget.py charge --turns 1 [--tokens N --cost-usd X]` — **exit 3 means budget exhausted → stop.**
   - Do one unit of work *inside `$WT`* (read a failure, form a hypothesis, draft a fix). Pipe test output through `loop_logscan` for a structured pass/fail summary instead of eyeballing raw dots: `pytest | python3 scripts/loop_logscan.py` (returns `{ok, passed, failed, failing_tests, …}`; `ok` is False if it can't parse a summary — never claim green from unparsed output). **`loop_logscan` needs the test runner's pass/fail *summary* line** — use the project's normal test command and don't stack an extra `-q` on a project that already sets `-q` in `addopts` (it becomes `-qq` and suppresses the summary). If `matched` is False, your command hid the summary — fix the command, don't trust the run.
   - Append to the ledger (`loop_ledger.py append --section timeline|decision|hypothesis|needs-me`).
   - Periodically `loop_ledger.py compact` so the ledger stays small (structural; you do the
     semantic summary in the entry text).
4. **Disarm** — `python3 scripts/loop_budget.py disarm --status converged|budget-exhausted|stopped`.
   This removes the armed marker (hook goes inert again), appends a cost-log record, and stamps
   the ledger's `Status` with the final status so it stops reading `armed`.

### Shortcut: one-command read-only sweep

For the **diagnosis half** (watch → detect → report, no fixing), `loop_sweep.py` does the whole
arm → run-tests → logscan → ledger → report → disarm cycle in one command — cron/CI-friendly:

```
python3 scripts/loop_sweep.py --test-cmd "pytest" [--worktree "$WT"] [--report needs-me.md]
```

It runs the project's test command, summarizes via `loop_logscan`, writes findings to the ledger,
and emits a **needs-me report**. Exit **0 = green, 1 = red, 2 = couldn't parse** (so a scheduler
can act). It is **read-only — it never drafts a fix, commits, or merges.** Drafting the fix is the
agent's triage step (below), run as a deliberate follow-up on what the sweep surfaces.

The ledger — not the context window — is the loop's memory. Context is a finite attention budget
("context rot"); write decisions/findings/open-hypotheses to `LOOP-STATE.md` so a compacted or
restarted run loses nothing.

## The triage flow (the loop's inner step)

For each failure:
1. **Read** the failure (test output / log) — quote the exact error.
2. **Root-cause**, don't pattern-match the symptom. Record hypotheses as `hypothesis` entries.
3. **Draft the fix in the worktree only.** Never the main checkout (the hook enforces this).
4. **Verify adversarially** — re-run the failing test; have a fresh pass try to *refute* the fix
   (does it really fix the cause, or mask it?). Gate the draft through **`eval-first`**
   (match-or-beat-or-revert) and keep it behind **`flag-gate`** (default-OFF) — that is the trust
   gate the loop literature requires.
5. **Record the outcome** to the ledger; add a `needs-me` entry if a human must decide.

## LLM-aided log inspection

Aggregate pass/fail scores hide misbehavior. Read the *logs/traces*, not just the exit code —
catch out-of-scope or reward-hacking actions (e.g. an agent editing a test to make it pass instead
of fixing the bug). Surface anything suspicious in the needs-me report rather than silently
trusting a green checkmark. `scripts/loop_logscan.py` is the deterministic floor of this step —
it extracts counts + failing node IDs and refuses to report `ok` from output it couldn't parse;
*you* still read the trace for behavioral red flags scores can't see.

## Stop conditions

Stop on the first of: **budget exhausted** (`charge` exits 3), **converged** (a full pass finds no
new actionable failures — loop-until-dry, ideally 2 consecutive dry passes), or **needs-me** (a
decision only a human should make). Never "stop when it feels done" — the condition must be
explicit.

## Safety (deterministic, not prose)

While a loop is armed, the PreToolUse hook (`scripts/loop_hook.py`, registered in plugin.json)
**blocks**: `git push`, `git merge`, `git rebase`, `git reset --hard`, `git branch -d/-D`,
`git worktree remove`, and any `Write`/`Edit` outside `--worktree`. It is **inert when no loop is
armed**, so it never touches your normal manual work. Domain-specific blocks (e.g. "never call a
live trading API") belong in a *domain* PreToolUse hook, not here.

## Dogfood example (hephaestus itself)

```bash
WT=$(mktemp -d); git worktree add "$WT" HEAD
python3 .../loop_budget.py arm --goal "triage pytest failures" --max-turns 15 --worktree "$WT"
python3 .../loop_ledger.py init --goal "triage pytest failures" --run-id "$(date +%s)" --out "$WT/LOOP-STATE.md"
# loop: (cd "$WT" && pytest -q) → triage each failure → draft in $WT → verify → ledger
python3 .../loop_budget.py disarm --status converged
git worktree remove "$WT"
```

## Output — the needs-me report

End every run with a short report drawn from the ledger:
- **Run:** id · final status · budget spent (turns/tokens/cost).
- **Fixed (drafted in worktree):** each failure + the draft fix + verification result. *Drafts
  only — nothing merged.*
- **Needs-me:** decisions/failures that require a human, each with the evidence.
- **Suspicious:** anything log inspection flagged.

## Guardrails

- **Single-threaded.** No persona role-teams. Fan-out only for read-only breadth, never recombined.
- **Turns are the hard ceiling.** Tokens/cost are optional soft inputs — never the only guard.
- **Worktree-only, never merge/push/touch-production.** Enforced by the hook; design to it anyway.
- **The ledger is the memory.** Don't rely on the context window surviving a long loop.
- **Cheaper model/effort for the sweep.** Don't default to the most expensive setting.
- **Trust gate before any fix counts:** eval-first (match-or-beat-or-revert) + flag-gate (default-OFF).
