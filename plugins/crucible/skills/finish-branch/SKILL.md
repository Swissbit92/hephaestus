---
name: finish-branch
description: Close out a feature branch or worktree safely — gates on tests (no green, no merge), offers merge / open PR / keep / discard, defaults to a PR for deploy/protected targets, and cleans up without losing unmerged work. Use after implementation is done, or when the develop workflow reaches its INTEGRATE phase.
---

You integrate finished work back to its target and clean up — without ever silently
losing commits or pushing to a protected branch by surprise. You never pick the
integration action for the user.

## Phase 1 — Gate on evidence (no exceptions)

**Ask the repo what counts as proof before assuming it is a test run.** In a repo with a
suite it is; in one without, "tests green" has no referent and the gate silently becomes a
no-op that reports success because nothing failed — which is a different claim from *it
works*.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/evidence_gate.py" --repo . --base <target>
```

`0` = a contract exists and the applicable classes are printed · `2` = **could not
determine** (a declaration is present and malformed — fix it, never delete it) · `3` =
**nothing to gate on**: no `.crucible/evidence.json` and no runnable gates. Exit 3 is a
SKIP, not a pass, and it must be said out loud before any option is offered.

The contract resolves in one of two ways, and you do not choose it:

- **Declared** — `.crucible/evidence.json` lists classes (`when` / `evidence`, optionally
  scoped by `paths`). `--base` narrows to the classes this diff actually triggers.
- **Implied** — no declaration, but the repo has runnable gates, so the class is "the
  repo's own test gates pass, with no regression against the branch point". This is the
  pre-existing behaviour and needs no configuration.

Then run what the applicable classes demand — for the implied class that is the repo's
test command, compared against the baseline `start-branch` recorded.

**Record a verdict word, not a tick.** Three outcomes, never two:

| Verdict | Meaning | Effect on the options |
|---|---|---|
| `pass` | every applicable class produced its evidence, and you can name it | all four options available |
| `fail` | evidence was produced and it was negative | **merge and PR are off the table** — only keep and discard |
| `could-not-check` | the evidence could not be produced *here* — no second peer, no device, wrong platform | **merge and PR are off the table by default.** It may be overridden, but only by the user, out loud, with the gap named |

`could-not-check` is the reason this phase exists. Folding it into `pass` is how an
unverified change acquires a green tick, and folding it into `fail` is how a gate that
cannot run on this machine becomes an accusation. Name it, and say what would settle it.

If the reason you cannot check is that the *environment* is misbehaving rather than absent —
calls succeeding while nothing happens — that is a session-level stop with its own signal:
`act-for-real`'s [blocked-signal](../act-for-real/references/blocked-signal.md). A session
that emitted it and then recorded `pass` has contradicted itself.

A pass that cannot name its evidence is not a pass, it is a feeling.

## Phase 2 — Resolve the target, then confirm what's being integrated

**Read the recorded target before detecting one:**

```bash
git config --get branch."$(git rev-parse --abbrev-ref HEAD)".integrationTarget
```

If it is set, `start-branch` wrote it when the branch was created — including the case
where the branch model was ambiguous and the *user* resolved it. Prefer it over
re-detection: re-running the heuristic can pick a different branch than the one this work
actually forked from, and integrating into the wrong target is not a mistake that
announces itself.

If it is unset (an older branch, or isolation was done by hand), fall back to detecting
the model exactly as `start-branch` does, and **say which way you got the answer** — a
detected target is a guess the user should be given the chance to correct, a recorded one
is not.

Show the user exactly what would move:

```
git log --oneline <target>..HEAD
git diff --stat <target>..HEAD
```

If the current branch **is** the integration target (e.g. isolation was declined, or no
branch was created), **stop** — there is nothing to integrate, and you must not try to
merge a branch into itself. Say so and exit.

## Phase 3 — Let the user choose (never decide for them)

Present four options:

1. **Merge** — fast-forward or `--no-ff` merge into the target (only if Phase 1 was green).
2. **Open PR** — push the branch and open a pull request against the target.
3. **Keep** — leave the branch as-is for later.
4. **Discard** — delete the branch and its work.

**Deploy safety:** if the target is a deploy/protected branch, default to **Open PR**,
not a direct merge/push. Never push to a protected branch without a separate, explicit
confirmation that names the branch and states the consequence.

**Informed discard:** before discarding, enumerate exactly what will be lost — list the
uncommitted files and the unmerged commits (`git log --oneline <target>..HEAD`). Only
proceed on explicit confirmation. On confirmation, the discard may use `git branch -D`
(an unmerged branch is the whole point of discarding, and `-d` will refuse it) — but
*only* here, *only* after this confirmation.

## Phase 4 — Clean up safely

- **Merge / Keep paths:** delete a merged branch with `git branch -d`, which refuses to
  delete a branch not merged into its upstream or HEAD — a safety net that catches "I
  thought this was merged." Never use `git branch -D` on these paths.
- **Discard path only:** discarding an *unmerged* branch genuinely requires
  `git branch -D` (`-d` will refuse it). Use `-D` **only** after the Phase 3 informed-
  discard confirmation that listed the commits being lost — never silently, never on any
  other path.
- Remove a worktree with `git worktree remove`. A dirty worktree needs `--force`, which —
  like `-D` — is allowed only on the confirmed Discard path; otherwise surface the dirt
  rather than forcing.
- Leave remote-branch deletion to the forge's auto-delete-on-merge setting rather than
  scripting a force-delete.

## Guardrails

- **No green, no merge.** A failing or regressed test run blocks merge and PR, every time.
- **Never lose work silently.** Dirty tree or unmerged commits → prompt first; force-delete
  (`-D` / `--force`) only on the confirmed Discard path.
- **Never push to a protected/deploy branch by surprise.** PR by default; direct push
  only on explicit, named confirmation.
- **Never choose the action for the user.** Present the options; let them decide.
