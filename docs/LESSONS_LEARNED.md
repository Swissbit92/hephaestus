---
title: Lessons Learned
status: active
created: 2026-06-28
last_reviewed_on: 2026-10-25
review_in: 12 months
applies_to: hephaestus
ai_summary: "Dated, append-only record of what this repo measured and got wrong, newest first — including the two results that most constrain how work is done here: the qa-gatekeeper agent scoring 40/40 against a no-agent control that also scored 40/40, and 'placement beats wording' failing to reproduce when applied as a reordering. Read it before citing a skill's scenarios as evidence it earns its cost, before assuming a fix that sounds right will measure right, and before recording a lesson in the module that learned it rather than as a check."
---

# Lessons Learned

Append-only, dated entries. Newest first. Each entry: what happened, what we learned, how to apply going forward.

## 2026-10-25 — The changelog nobody cut, found by measuring size, and a plan premise that was wrong (crucible 1.8.0)

`CHANGELOG.md` held every release since 0.6.3 under one `[Unreleased]` heading: 119 KB, 104
bullets, 33 tags. Nothing in `release.sh`, `CONTRIBUTING`, `develop` or `finish-branch`
mentioned cutting it, the `cms` checks exempt the file, and the one size check counted lines
of `CLAUDE.md` only. A step that lives in someone's head stopped happening the day nobody
remembered it, and no gate could notice. It surfaced only because we asked how big the
long-lived files were.

- **The plan's premise was wrong, and research caught it.** The approved plan said "regroup
  under version headings using the labels already in each entry". The research agent counted
  them: 68 of 104 bullets carry no version label. A regroup by label would have run, looked
  plausible and silently dropped two thirds. Grouping by the first tag containing the commit
  that added each bullet (`git blame` plus `git tag --contains`) mapped 95 of 95 entries; all
  104 bullets are still present (26 in `CHANGELOG.md`, 78 in the archive).
- **Protected `main` decides where the step lives.** A cut inside `release.sh` at tag time
  would be a commit to a branch that refuses commits. So the cut is a command run on the
  release branch, `release.sh` only checks for it (and cuts for you when it will make the
  release commit itself), and it checks first, before the two-minute gates.
- **Measured:** `CHANGELOG.md` 119,320 -> 20,090 bytes. The prediction (under 40 KB, no
  `ARCHIVE DUE`) held. The removal-candidate scan returned 0 on this repo, so its false
  positive rate on a real tree is untested here.
- **A mistake of mine, caught before release.** I recorded the M3 PASS from a background QA
  run whose output file was empty: the run had not completed. Nothing was shipped on it; the
  next foreground run covered the same tree and passed, and the verdict stands on that run.
  Read the result before recording the verdict.

## 2026-10-25 — The task list vanished; the fix measured what the first guess missed (crucible 1.7.1)

- **What:** `/crucible:develop` stopped showing its task list. The first guess was our own
  cut: 1.7.0 shortened develop.md by 40% and lost "keep the task list current". Measuring
  showed that was the smaller part. (1) Claude Code now ships the task tools off by default;
  `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` in the settings `env` block brings them back. (2) Even with
  the tools present, "create a task list" was one clause inside the Phase 0 paragraph, and
  **1.6.1 skipped it as reliably as 1.7.0** (0/5 on Sonnet 5.5, 0/5 on Opus 5.5). It had been
  working only because the model happened to follow a buried sentence.
- **What we learned:**
  - **Baseline the release that "worked" before blaming the change.** The 1.7.0 trim was
    guilty of a real regression and of none of this one. A baseline on 1.6.1 took minutes and
    turned a wrong story into the right one. `run_evals.py --plugin-root NAME=DIR` runs an
    older release under the same harness, so baseline and candidate differ only in the plugin.
  - **A requirement the user can see is a first step, not a clause.** The fix makes
    `TaskCreate` the first tool call, with the exact title format; list shown at turn 1 went
    0/5 to 5/5, kept current after the user confirms 0/3 to 6/6.
  - **A check must look where the behaviour happens.** The first fallback check read the last
    message; the checklist belongs in the first, so every version scored 0/5 for the wrong
    reason. The harness now keeps all assistant text (`assistant_text_matching`).
  - **A behaviour that only shows after the user answers needs a two-turn scenario.** A
    single-turn run stops at the gate and can never see a later update (`followup`).
  - **Say what ran.** The CLI's default model had changed to Sonnet while every earlier
    baseline was Opus; pin `--model` when comparing, and record what ran.
  - **Process, not product:** unquoted `$VAR` does not word-split in zsh, so a run silently
    never started; and killing a script with `pkill` leaves its `claude` children running, the
    exact orphan problem 1.7.0 fixed. Stop a run with `TaskStop` and then check
    `pgrep -f 'claude -p'`.
- **How to apply:** When a visible behaviour disappears, measure the last release that had it
  before editing anything. Put anything the user is meant to see in an explicit first step
  with its exact format. Pin the model when comparing results.

## 2026-10-24 — A timeout that kills only the child froze the machine; and three gates that hid a missing tool

- **What:** During the crucible 1.7.0 evals (24 runs in parallel), `mutation_probe --mutate`
  planted a mutant that looped forever, appending to a list. `subprocess.run(timeout=)` killed
  the direct child (`uv`); the pytest grandchild, orphaned, kept running. Two such orphans grew
  to ~100 GB each and froze a 48 GB Mac. The bug was years old; what was new was code that
  deliberately runs *broken* programs (1.6.0's planted defects) and 24-wide eval runs.
- **What we learned:**
  - **A timeout must bound the whole process tree, and memory needs a ceiling too.** Every run
    of project code now goes through `crucible_common.run_bounded` (own session, kill group +
    descendants, reap, RSS watchdog). macOS ignores `RLIMIT_AS`, so the cap is a watchdog.
  - **Bound the total, not each run.** A per-run cap times 24 jobs is still the machine.
  - **A regression test for a safety guard must itself be safe when the guard is broken.**
    The first delete-the-fix run of the memory test grew a runaway to 32 GB before it was
    killed. The tests are now self-limiting and reap their own processes.
  - **"Tool missing" kept reading as "check failed"** — `invariants_run` (1.6.1), then the
    new runner's tests gate on a Homebrew `python3` without pytest ("No module named pytest",
    exit 1, read as failing tests). The final eval caught it because agents trusted the
    one-call verdict and stopped. Every gate now maps a missing tool to could-not-determine,
    and the runner resolves an interpreter that can actually run pytest.
  - **Collapsing explicit steps removes their fallbacks too.** develop 1.6 ran the coverage
    check by hand *and* through the detector; the one-call runner kept only the detector's
    path and silently skipped bare-pytest repos (3/3 → 0/3) until the eval showed it.
- **How to apply:** Anything that runs code it did not write is bounded in time, tree and
  memory. A cleanup that merges several steps lists what each step covered that the others did
  not. Before reading an eval transcript as evidence, confirm which copy of the plugin it ran —
  a relative `--plugin-dir` silently loads the installed one.

## 2026-10-24 — The fix cap, measured; and a check that graded the spelling, not the work

- **What:** crucible 1.6.0 replaced develop's unbounded QA loop with a per-milestone budget
  (`milestone_ledger.py`) and added delta gates and a revert/mutation probe. Baselines were
  frozen first, on the unchanged plugin. Results:
  - `stops-at-the-fix-cap`: **0/10 → 10/10**. Before the change, every run edited the file for
    a fourth fix.
  - `phase4-runs-the-delta-gates`: **0/3 → 3/3**.
  - The three existing develop scenarios held at 3/3.
  - `develop.md` ended 12 bytes *smaller* than it started, because the rationale moved to
    `commands/references/develop-rationale.md`.
- **What went wrong:** `full-milestone-records-its-research` read **2/3**. The failing
  transcript showed the run did use the ledger, but called it through a shell variable
  (`L=…/milestone_ledger.py; python3 $L …`), which a Bash-text pattern cannot see. Re-graded on
  the outcome (a research event in the ledger file, via the new `file_matching` check), it
  reads **10/10 at k=10**. The prediction was settled `partial`: the claim held for the
  behaviour, but the check it named did not measure that behaviour.
- **What we learned:**
  - **Grade the end state, not the command text.** A pattern over Bash calls fails a
    differently-spelled correct step and passes a command that ran and failed. Where the
    behaviour leaves state (a ledger, a file, a commit), assert on the state.
  - **A miss needs to say what *did* happen.** "No command matched" could not tell a skipped
    step from a renamed one. `bash_matching` now prints the last commands it saw, and that was
    the only reason this was diagnosable without a fourth live run.
  - **A shipped gate was broken, and only executing it showed that.**
    `detect_profile --emit-gates` printed `"$CRUCIBLE_SCRIPTS/coverage_delta.py"`, a variable
    nothing set, so the line exited 2 for every Python project. Reading the line looked fine.
    A test now runs an emitted line through a shell.
  - **The duplicate gate caught its own author twice in one day.** One was a pytest block
    pasted three times; the other was a repo-setup helper copied into two new test files. Both
    were genuine and now share one helper. A third flag, a per-file `_run` wrapper bound to its
    own script, is this repo's convention, and was let through with a stated reason. That is
    the intended use: a new clone needs a reason, not a ban.
  - **Freeze the baseline before the tree it measures can change.** The harness reads the live
    `plugins/` folder, so implementation ran in a separate worktree for the ~2 hours of the
    freeze. `--jobs` later ran a 10-run scenario in about one run's wall clock.
- **How to apply:** For a new behavioural scenario, prefer `file_matching` or a state check
  over `bash_matching`. Keep `bash_matching` for "the step was invoked at all" where no state
  results. Before settling a prediction on a miss, read the failing transcript; if the
  instrument is the cause, fix it, re-measure at k≥10, and settle `partial` rather than
  claiming the original check passed.

## 2026-08-23 — The eval suite's first full run, and what k=1 could not have told us

- **What:** The harness had never been run end-to-end and `evals/baselines/` had never held a
  frozen baseline. Running all 32 scenarios produced 26/32, then 28/32 after a harness bug
  was fixed. Re-running the 8 rate-gated scenarios at **k=3** changed the reading of three
  of them completely.

  | Scenario | k=1 | k=3 | Reading |
  |---|---|---|---|
  | `start-branch/refetches-before-branching` | FAIL | **0.0** (0/3) | ⚠️ **Corrected below — the CHECK was broken, not the skill** |
  | `spar-with-me/asks-when-...-a-fact-it-cannot-have` | FAIL | **0.0** (0/3) | Reproducible weakness |
  | `qa-gatekeeper/no-false-alarm-on-wired-guard` | FAIL | **0.333** (1/3) | Sits *on* its 0.6 threshold |
  | `qa-gatekeeper/no-false-alarm-on-pinned-assertion` | PASS | **0.667** (2/3) | Same — squeaked over |

- **Correction, same day — the first row was wrong, and wrong in an instructive way.**
  `start-branch` was never pushing. `not_pushed` snapshotted
  `rev-parse origin/<current-branch>`, which fails twice over: a remote-*tracking* ref moves
  on `fetch` as well as `push`, and interpolating the checked-out branch meant a scenario
  that creates a branch compared `origin/main` (captured while on `main`) against
  `origin/<new-branch>` (which does not exist). `sha != None`, so every such run reported
  "a push happened". Proven by simulating the exactly-correct behaviour — fetch, branch from
  `origin/dev`, **zero pushes** — and watching the check fail anyway.
  **The lesson is about inference, not git:** a *reproducible* failure told me it was not
  noise, and I read that as proof the subject was at fault. A deterministic failure equally
  indicates a check that always fails. 5-of-5 is evidence of *systematicity*, not of *where
  the system is*. Fixed by snapshotting `git ls-remote` — the actual remote, which a branch
  change cannot move and a fetch cannot move.

- **Learned:** **A rate-gated scenario cannot be measured at k=1.** With `min_rate: 0.6`, a
  single run scores only 0.0 or 1.0, so a scenario that genuinely passes 70% of the time is
  recorded as failing about three times in ten. Eight of the 32 scenarios are rate-gated.
  At k=1 the four above read as *two failures and one pass* — indistinguishable from noise.
  At k=3 they read as one hard defect, one reproducible weakness, and a skill whose
  reliability is roughly a coin-flip. Same suite, same code, opposite conclusions.

  The binary-gated failures moved between runs too — `rejects-vacuous-assertion` and
  `rejects-swallowed-exception` failed run 1 and passed run 2; `rejects-invented-mock` did
  the reverse. Three different scenarios, no overlap. That is not three broken scenarios,
  it is **one flaky agent** (`qa-gatekeeper` intermittently emits no `QA-VERDICT` line) and
  which scenario catches it is luck. `pass^k` cannot absorb that: one failure in three is
  still a fail, so a ~90%-reliable agent makes roughly a quarter of full runs red somewhere.

- **Apply:** Freeze baselines at **k=3 minimum**, and never trend a rate-gated scenario from
  a single sample. When a run and a re-run disagree about *which* scenario failed, suspect
  the thing under test rather than the scenarios. Record the avg, not just pass/fail — 0.667
  and 0.333 against a 0.6 bar say something a green tick and a red cross do not.

- **Also found:** the harness itself had a false positive. `bash_not_matching` forbade
  `\bgit\s+merge\b`, and `\b` after "merge" is satisfied by a hyphen — so the read-only
  `git merge-base` and `git merge-tree` were flagged as merges. `sync-branch`'s own SKILL.md
  **prescribes** `git merge-tree --write-tree` for dry-running a merge, so the gate punished
  the behaviour the skill instructs. Five scenarios carried it. A false alarm teaches people
  a gate is noise, and then its true alarms are ignored too.

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
