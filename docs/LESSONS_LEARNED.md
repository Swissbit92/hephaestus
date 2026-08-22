---
title: Lessons Learned
status: active
created: 2026-06-28
last_reviewed_on: 2026-06-28
review_in: 12 months
applies_to: hephaestus
ai_summary: "Dated, append-only record of what this repo measured and got wrong, newest first — including the two results that most constrain how work is done here: the qa-gatekeeper agent scoring 40/40 against a no-agent control that also scored 40/40, and 'placement beats wording' failing to reproduce when applied as a reordering. Read it before citing a skill's scenarios as evidence it earns its cost, before assuming a fix that sounds right will measure right, and before recording a lesson in the module that learned it rather than as a check."
---

# Lessons Learned

Append-only, dated entries. Newest first. Each entry: what happened, what we learned, how to apply going forward.

## 2026-08-22 — A check you have never watched fail is not a check

- **What:** Three prediction-ledger entries were settled `partial` or worse, and in all
  three the *claim* was fine — the **instrument** was broken. The clearest case: a
  prediction that a fresh clone and the working copy would report identical archive
  findings, whose check was "run `check.py` on both and diff". hephaestus contains zero
  files matching `ARCHIVE_PATTERNS`, so the check returns `0 == 0` before the fix and
  `0 == 0` after. It could not have distinguished a working implementation from a broken
  one, and nobody noticed, because it was never run against the unfixed tree. The two
  earlier cases both turned on `ast.parse(feature_version=…)` silently not measuring what
  the author assumed.
- **Learned:** `predictions.py` already enforced the two rules that guard the *claim* —
  a check is mandatory, and a recorded claim is immutable. Neither says anything about
  whether the check could ever fail, which is a separate defect with an identical result:
  a settled entry carrying the full appearance of rigour and none of the content. The
  reason it is invisible from the writing chair is structural, not careless — a check is
  written *after* the author understands the problem, so it is born green and is never
  once observed failing. This is exactly the defect TDD's first step exists to prevent
  ("a test that has never been red proves nothing when it turns green"), and exactly what
  research methodology means by "a pre-registration that cannot fail is not a
  pre-registration". Two fields independently derived the same rule; this repo derived it
  a third time, the expensive way.
- **Apply:** `record` now refuses without `--baseline` — what the check shows *right now*,
  on the unchanged tree. Stating it forces the check to be run at the one moment its
  validity is observable. Entries predating the rule are listed as `baseline: NOT
  RECORDED` rather than quietly counted as equivalent. Generalise beyond the ledger: when
  you add any gate, reintroduce the defect and watch it fail before you trust it green —
  that is how the mtime guard below was validated, and it is why `test_mtime_guard.py`
  carries an explicit mutation test.
- **Found while fixing it:** the `--check` refusal message had been **unreachable since it
  was written**. `required=True` means argparse rejects a missing flag first, with exit 2
  — the code this script documents as "the store is unreadable or malformed" — so a
  forgotten flag was indistinguishable from a corrupt ledger, and the carefully-worded
  explanation had never been displayed to anyone. A guard behind `required=True` is not a
  guard. Found only because the new baseline rule was tested by running it.

## 2026-08-22 — A lesson recorded where it was learned does not travel

- **What:** `render.py` discovered that git does not preserve mtimes ("which fired on the
  first merge of this tool") and wrote that into its own docstring. The lesson stayed
  there. The cms archive rule then made the identical mistake at **four** further sites:
  `check.py` (candidacy), `migrate.py` twice (candidacy again, independently
  re-implemented, and the `YYYY-MM` archive folder name), and `add_frontmatter.py` — which
  *wrote* an mtime-derived `created:` date into frontmatter, where it then fed `review_in`
  staleness forever. The rule was completely non-functional on every clone for an unknown
  period, and the suite stayed green throughout because all three tests of the age branch
  faked age with `os.utime`, asserting against a filesystem state git never produces.
- **Learned:** The failure was not that the lesson was unrecorded — it was recorded, in
  prose, accurately, next to the code that learned it. It was that prose in one module has
  no mechanism for reaching the author of another. Note also that this was never a matter
  of local cleverness: the reproducible-builds specification states the same constraint and
  prescribes the same remedy (use the last git commit timestamp, because individual file
  timestamps cannot survive a checkout). The information was available in two places and
  reached neither of the four sites.
- **Apply:** The rule is now an invariant with an executable check
  (`scripts/checks/mtime_is_never_a_clock.sh`), so it is enforced rather than remembered.
  It parses rather than greps, deliberately: `doc_age.py` — the module that *fixed* the
  bug — discusses `st_mtime` throughout its docstring, and a rule whose first action is to
  accuse its own remedy is one people switch off. The allowlist requires a stated reason
  per entry, because an allowlist without reasons is just a place to put inconvenient
  findings. The general form: when a lesson is worth a docstring, ask whether it is worth
  a check — the ones that recur are the ones no one will read the docstring for.

## 2026-08-10 — The review half of the QA gate is unproven; the deterministic half isn't

- **What:** `qa-gatekeeper` measured against a no-agent control on its own four defect
  fixtures, k=10 per arm, 80 runs. **Treatment 40/40. Control 40/40.** The bare prompt
  *"Review this branch before I merge it. The suite is green."* found every seeded defect —
  wrong arithmetic behind a vacuous assertion, a mock contradicting a checked-in vendor doc,
  a guard assigned but never called, a swallowed write — with the `Agent` tool invoked
  **0/10 in every control arm**, so it was not quietly auto-routing to the agent either.
- **Learned:** The agent is reliable and adds nothing measurable. Its scenarios were never
  evidence that it works — they show it does not regress, which is a weaker and different
  claim. This was invisible for months because every scenario asserted
  `subagent_verdict == REJECT`, a check a control cannot even produce, so the comparison that
  would have exposed it was structurally unavailable.
- **Apply:** Do not cite the gatekeeper scenarios as evidence the agent earns its cost. When a
  scenario's assertion is *only* satisfiable by the thing under test, that is a smell, not a
  virtue — it means no control can be run, and an unrunnable control is an unfalsifiable
  claim. Note the contrast that matters: Phase 4.0's deterministic checks were separately
  measured and **do** beat the prose alternative (3/6 → 2/6 → 3/3). What carries `develop` is
  the scripts it executes, not the review it delegates.

## 2026-08-09 — "Placement beats wording" is not "reorder the instructions"

- **What:** `spar-with-me`'s Q&A step reaches a genuine discriminating question **3 times in
  10**, identical to a run with no skill at all. Citing this repo's own placement-beats-wording
  result, the step was moved from after the research to before it, the permission to skip was
  replaced with a forced disclosure, and a contradicting anti-pattern was fixed. Re-measured on
  the same fixture, same prompt, same k: **3/10. Unchanged.** Reverted.
- **Learned:** The Phase 4.0 result (agent-told-to-run 2/6 → workflow-runs-it 3/3) came from
  moving work out of **instruction** and into **execution**. Reordering steps inside a prose
  document is not that — it is the same document, the same reader, and the same request, just
  in a different order. Conflating the two produced a change that read like a principled fix
  and moved nothing. A prose step that fires 30% of the time is unreliable *as prose*, and no
  arrangement of prose repairs it.
- **Apply:** Before invoking "placement beats wording", ask whether the change moves the work
  to something that *executes* — a script, a hook, a tool the workflow itself runs. If the
  agent is still being asked, it is a wording change; predict accordingly and measure before
  believing it. Corollary for this case: fixing the Q&A step needs a turn boundary the skill
  cannot currently create, and the single-shot harness cannot even represent *ask and wait* —
  it only sees whether a question was emitted. The defect is real, measured, and **currently
  out of reach**; it is recorded rather than papered over.

## 2026-06-28 — Repository initialized

- **What:** `/cms init` scaffolded the standard doc set.
- **Learned:** Creation-time enforcement is the strongest lever for doc hygiene (Nx, Kubernetes OWNERS, Backstage).
- **Apply:** Any new repo starts here. Retroactive audits drift; creation-time templates don't.
