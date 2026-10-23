---
description: Why develop's rules are shaped the way they are — the evidence behind each step. Reference material for develop.md; not an invocable command (it sits under commands/ only so develop.md can link to it relatively).
disable-model-invocation: true
---

# develop — the reasons behind the rules

`develop.md` holds the instructions. This file holds the reasons, so the workflow stays
short enough to follow while the evidence stays one link away. Read a section when a rule
looks like ceremony; each one was paid for.

## Phase 1 — start with the routing table

Searching a repo's docs by opening likely-looking ones costs the full text of everything you
opened and were wrong about, so the price of orienting scales with the size of the corpus
rather than the size of the answer. `triage.py` prints path, status and summary for every
document that has one; documents with no summary are listed too, so the table cannot quietly
route you around the part of the corpus it cannot see.

## Phase 2 — why record a prediction

Every change in a repo was justified at the time. What a repo never accumulates is evidence
about whether the justifications were *right*, because the prediction is made here and the
outcome arrives weeks later somewhere else, and nothing puts the two side by side. The result
is a codebase where every decision looked sound and the overall direction cannot be
evaluated. Thirty seconds at plan approval is the whole cost of fixing that.

**Falsifiable or not at all.** "This will improve quality" cannot be wrong and so is graded
correct in hindsight, every time. "The hook will block frontmatter errors that CI would
otherwise catch a day later, and I expect at least one in the next ten skill edits" can be
wrong, which is the only reason to record it. The script refuses a prediction with no
`--check` for exactly this reason.

**A check you have never watched fail is not a check.** This is the rule the ledger paid
for: three entries were settled `partial` or worse where the *claim* was fine and the
**instrument** was broken. The clearest case predicted that a fresh clone and the working
copy would report different findings, and specified "run the linter on both and diff" — in a
repo containing no file the rule could ever match, so the check returned `0 == 0` before the
fix and `0 == 0` after. It could not have told success from failure.

The reason this is structural rather than careless: a check is written *after* you
understand the problem, so it is born green and is never once observed failing. Test-driven
development has the same first step for the same reason — a test that has never been red
proves nothing when it turns green — and research methodology says it as "a pre-registration
that cannot fail is not a pre-registration". `--baseline` is refused when empty precisely so
the check gets run at the one moment its validity is observable.

## Phase 2 — why a fix budget

The loop this replaced was "REJECT → fix, re-run QA; do not proceed until PASS": no cap, no
stop condition. In real use a single milestone ran about seven rounds and ten agent-hours
past its budget, and the same-failure-twice rule meant to catch that never fired, because
every round failed for a different reason and so looked like progress. A study of CLI
coding-agent trajectories reaches the same point from the outside: once a recovery runs past
the length of a typical successful one, further repair rarely helps. So every REJECT counts,
setup failures get their own budget (a broken toolchain must not spend the fix budget), and
at the cap the decision goes to the user — ship, continue, or restart from the plan, where a
fresh attempt has been measured to beat continued self-repair at the same budget.

Per-milestone research runs in parallel with the build because, in two projects that tried
it, it changed decisions mid-run — a published number found quoted backwards, a design
switched after every comparable system was found to have shipped the same bug — at about
ten minutes of wall clock per milestone. As a prose step it gets skipped, which is why the
ledger refuses to close a FULL milestone without it.

## Phase 2.5 — why the integration target is recorded

Detection is a heuristic and the user's correction is the only authoritative part of it, yet
it is the part that evaporates: later phases re-derive the target in a session that may not
be this one, and in a repo with both `dev` and `main` they can land on a different branch
than the one the work forked from — and then the gate compares against the wrong baseline
while looking entirely healthy. Writing it into git config makes the answer outlive the
conversation; the gate scripts read it through `crucible_common.detect_target`.

## Phase 4.0 — why the checks are scripts, run by you

**Capabilities are never emitted as gates.** A browser suite whose config starts no server,
run against nothing, collects zero tests and exits clean — and zero tests passing is not a
pass. That is why the gate/capability split lives in the tool rather than in judgement.

**Invariants are executed, not restated.** A constraint stated once is least salient
exactly when it is about to be broken, and restating it does not help: the thing doing the
forgetting is the thing being asked to remember. A script does not care how long ago the
rule was written.

**Why this sits in the workflow and not in the gatekeeper's instructions: it was
measured.** Asking the agent to compare test sets by eye caught a green-but-shrunken suite 3
times in 6; giving it the script and asking it to run the script caught it 2 times in 6. The
check was never the weak part — the *request* was. A step the workflow executes runs every
time; a step an agent is told to perform runs sometimes. Put deterministic checks on this
side of that line.

**Delta gates compare sets, not counts.** An absolute lint gate fails forever in a codebase
that already carries findings (one had 2,122 at the branch point), so it is ignored; a count
gate cannot see one finding swapped for another. Comparing finding identities at the current
merge-base fixes both, and the merge-base moving forward is the ratchet — no stored file.

**Delete the fix before trusting the test.** A green suite says the tests agree with the
code, not that they would disagree with a broken version of it. Restoring the branch point's
code and watching the changed tests fail is the cheapest proof they test the change; planted
defects are the stronger one, kept to the final milestone because each costs a test run.
