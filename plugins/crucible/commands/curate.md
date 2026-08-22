---
allowed-tools: ["Read", "Glob", "Grep", "Bash"]
description: "Maintain the fabric rather than a feature — a periodic pass over a repo's skills, docs, recent changes and open predictions that produces a ranked backlog. Use on a cadence (monthly, or after a burst of work), not per change. For building something, use develop."
---

# Curate — the maintenance pass

`develop` builds things. Nothing maintained them.

That gap has a name in the literature and a measured cost: **skill technical debt** —
redundancy, missing validation, interface drift, stale implementations. None of it breaks a
skill locally, all of it degrades retrieval and composition later, and none of it is
introduced by a diff anyone could have rejected. It only ever accumulates. A rule-based
maintenance loop over a 200-skill library beat the strongest baseline by ~9 points at
essentially no per-task model cost, because the diagnosis is *counting*, not judgement.

So this pass is deterministic first and judgement last. Run the scripts, then think about
what they found — never the other way round.

**Cadence:** monthly, or after a burst of work. Running it per change is how a maintenance
routine becomes noise people skip.

---

## Phase 1 — Collect the facts (scripts only, no judgement yet)

Run all of these and keep the raw output. Every one is deterministic: same repo, same
commit, same answer. A non-zero exit is a finding, not a failure of the pass — except `2`,
which everywhere in this repo means *could not determine* and must never be recorded as
clean.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/skill_lint.py" --strict --show-duplicates
python3 "${CLAUDE_PLUGIN_ROOT}/skills/cms/scripts/triage.py" --repo .
python3 "${CLAUDE_PLUGIN_ROOT}/skills/cms/scripts/check.py" .
python3 "${CLAUDE_PLUGIN_ROOT}/skills/repo-audit/scripts/repo_metrics.py" . --json
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/predictions.py" list
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/invariants_run.py"
```

If the repo keeps a note vault and the `second-brain` plugin is installed, add its
`scripts/vault_graph.py <vault>`. Resolve it from that plugin's own root rather than
relative to this one — installed plugins are not necessarily siblings on disk.

Record each exit code in the report. **A skipped script is not a passing script** — say
which ones did not run and why.

## Phase 2 — Read the library across five dimensions

The scripts answer most of this. Judgement is only needed where a number has to become a
decision.

| Dimension | What the facts show | The question only you can answer |
|---|---|---|
| **Utility** | skills never invoked; `develop` referencing few of them | is this unused because it is bad, or because nothing routes to it? |
| **Redundancy** | `skill_lint` overlap findings | equivalent preconditions *and* artifacts → merge; either differs → keep and disambiguate |
| **Staleness** | `cms check` review-by, `triage` summaries | has the world moved, or only the calendar? |
| **Validation gaps** | claims with no check behind them | which unverified claim would cost most if wrong? |
| **Drift** | docs describing something the code no longer does | is the doc wrong, or is the code? |

The merge rule is worth stating exactly, because "these feel similar" merges good skills:
**merge only when two skills take the same inputs and produce the same artifact.** If
either differs they stay separate and the *descriptions* get sharpened instead — an
overlapping description is a routing problem, and merging is not the only fix for it.

## Phase 3 — Recent changes

Run `refactor-audit` over the range since the last curate pass. That skill audits one body
of work for production-readiness; here it is answering a narrower question: **what did the
last month accumulate that nobody would have accepted deliberately?**

## Phase 4 — Settle what can be settled

Take the open predictions from Phase 1 and close every one whose check has now run.

This is the phase that makes the pass worth repeating. A prediction ledger with no `wrong`
entries is not a record of good judgement — it is a record of predictions too safe to be
informative, or of verification too generous to be a test. `predictions.py list` says so
out loud when it has never recorded a miss. **Treat that message as a finding about this
pass**, not as a compliment.

`list` reports a second thing worth acting on: how many predictions carry **no baseline** —
no record of what their check showed before the change. Those are the entries whose checks
were never observed failing, and a check that has never failed cannot be shown to
distinguish success from failure. Do not retro-fit a baseline; the tree it described is
gone, and inventing one is the same falsification as editing a claim. Instead, weight those
verdicts lower when reading the ledger's overall shape, and say so in the report.

## Phase 5 — The backlog

Produce a ranked list, and rank it by *cost of leaving it* against *cost of fixing it* —
not by severity, which flattens everything urgent-looking to the top.

Split it the way it will actually be consumed:

- **An agent can fix this unattended** — mechanical, reversible, covered by existing tests.
- **This needs a human decision** — it changes a public contract, contradicts a recorded
  decision, or trades one property for another.

Then write the pass down: what was measured, what was decided, what was deferred and why.
A curate pass whose findings are not recorded produces the same list next month, and the
month after, and reads as new every time.

## Anti-patterns

- **Judging before counting.** The scripts are cheaper and more consistent than reading;
  reversing the order wastes the cheap half and biases the expensive one.
- **Merging on resemblance.** Same-feeling is not same-interface. Apply the merge rule.
- **Fixing the threshold.** When `skill_lint --strict` fails, the skill moved, not the
  budget. The thresholds are pinned by tests so that relaxing one is a visible act.
- **A pass with no `wrong` verdicts and no deferrals.** That is a pass that measured
  nothing and decided nothing.
- **Running it per change.** This is a cadence, and one that fires too often gets skipped
  entirely.

Pairs with `develop`, which builds what this maintains; with `skill-craft`, whose `lint`
mode is Phase 1's first line; and with `repo-audit`, whose deterministic anchor this reuses
rather than duplicating.
