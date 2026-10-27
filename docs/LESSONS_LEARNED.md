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

> Older entries are archived: see the `LESSONS_LEARNED.md` files under [docs/archive/](archive/).
