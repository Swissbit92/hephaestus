---
name: finish-branch
description: Close out a feature branch or worktree safely — gates on tests (no green, no merge), offers merge / open PR / keep / discard, defaults to a PR for deploy/protected targets, and cleans up without losing unmerged work. Use after implementation is done, or when the develop workflow reaches its INTEGRATE phase.
---

You integrate finished work back to its target and clean up — without ever silently
losing commits or pushing to a protected branch by surprise. You never pick the
integration action for the user.

## Phase 1 — Gate on tests (no exceptions)

Run the repo's test command. Compare to the baseline `start-branch` recorded.

- Tests fail or regress vs. baseline → **merge and PR are off the table.** Only **keep**
  and **discard** remain. Say so plainly.
- Tests green and no regression → all four options are available.

## Phase 2 — Confirm what's being integrated

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
