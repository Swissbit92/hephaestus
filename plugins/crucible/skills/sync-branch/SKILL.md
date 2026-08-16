---
name: sync-branch
description: Keep an open feature branch current with its integration target without disturbing work in progress — dry-run the merge before taking it, classify the result as free, deferrable or a deliberate session of its own, and only ever sync at a green checkpoint. Use whenever the target has landed something, before gathering any expensive evidence, and always immediately before finish-branch. Not for merging back — that is finish-branch.
---

You keep a branch close enough to its target that the evidence gathered on it is still
evidence about the codebase people are actually running. You **never** sync a dirty tree,
you **never** discover a conflict by performing the merge, and you sync in one direction
only.

A branch one commit behind merges clean; a branch thirty commits behind is a rewrite. The
cost is not linear, and it falls due at the worst possible moment — when the work is
finished and everyone wants it in.

## This is a trigger, not a position in a sequence

There is no correct place for this in an ordered workflow, because the target moves while
you work. On one real branch the distance went 0 → 17 → 20 → 2 commits behind in a single
session, once mid-gate. Fire on the condition instead:

- **The target has landed something.** Check on returning to a branch, and at least daily
  while one is open.
- **Before any expensive evidence.** A two-peer run, a device test, a long benchmark —
  anything you would hate to repeat. Evidence gathered before a sync proves something
  about a tree nobody has.
- **Always immediately before `finish-branch`.** Its gate is only as good as the tree it
  ran on.
- **Not in the middle of an edit.** The one case where waiting is cheaper.

## Phase 1 — Refuse to sync a dirty tree

```bash
git status --porcelain      # must be empty
```

If it is not, commit or stash first. A sync into a half-finished edit mixes someone else's
conflict with your own unfinished thought, and afterwards nobody can tell which change
broke what. **The checkpoint, not the merge, is what protects work in progress.**

Confirm the branch is *green* before syncing too — whatever green means here
(`evidence_gate.py` says). Syncing onto a broken branch makes the next failure ambiguous.

## Phase 2 — Recover the target, don't re-detect it

```bash
git config --get branch."$(git rev-parse --abbrev-ref HEAD)".integrationTarget
```

`start-branch` wrote it, including the case where the model was ambiguous and the *user*
resolved it. Only if it is unset, detect as `start-branch` does — and say which way you got
the answer.

```bash
git fetch origin
git log --oneline --format='%h %an %s' HEAD..<target>
git diff --stat HEAD...<target> | tail -20
```

**Read the commit subjects.** Intent is what decides Phase 4 — "the harness stops assuming
it is running on a Mac" tells you a generalisation landed, which is the dangerous class.

## Phase 3 — Dry-run the merge; never discover it by doing it

```bash
git merge-tree --write-tree --name-only <target> HEAD
```

This prints the conflicts **without touching the tree**. It costs a second, and it turns
the decision below from a gamble into a lookup.

## Phase 4 — Classify, then act

| Dry run says | Overlaps files you are actively editing | Verdict |
|---|---|---|
| No conflicts | no | **Sync now.** It is free; there is nothing to weigh |
| No conflicts | yes | **Sync now anyway**, at the checkpoint. It only gets more expensive, and a clean merge into files you know well is the cheapest kind |
| Conflicts in generated/derived files only | — | **Sync now.** Resolve by regenerating, never by picking a side |
| Conflicts in code you are mid-rewrite on | yes | **Defer** to the end of this unit of work, then sync deliberately as its own commit |
| **The target generalised what you extended** (or the reverse) | — | **Stop. Book it as its own session.** This is the class that auto-merges into something wrong |
| Conflicts you do not understand | — | **Stop and ask.** An unexplained conflict is two people solving one problem, which is a conversation, not a merge |

The fifth row is the one worth memorising, and it is not theoretical. A target made a build
step cross-platform while a branch extended the platform-specific path. Both sides were
correct, the merge was textually clean where it mattered, and the result wrote a file to a
directory that no longer existed on half the targets — surfacing much later as a lookup
failure with no connection to either change.

## Phase 5 — Sync in one direction only

```bash
git switch <branch>        # or: cd <worktree>
git merge --no-edit <target>
```

**Always target → branch.** A branch's conflicts are resolved on the branch, where the
person who understands them is. Resolving them inside the target makes a bad resolution the
baseline every other branch then copies — and nobody reviews a merge commit as carefully as
they review a change.

Resolve generated regions by regenerating, never by hand: a hand-resolved generated file
disagrees with its source until the next generator run.

## Phase 6 — Re-verify; a sync is a change

An unverified sync is indistinguishable from your own regression a day later. Run what the
repo demands:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/evidence_gate.py" --repo . --base <target>
```

If the sync pulled in anything touching the classes you already discharged, **those classes
are undischarged again**. That is the cost of syncing late, and the argument for syncing
early.

## Phase 7 — Write one line where the work is tracked

```
Synced to <target> <sha> on <date> — <what conflicted, or "clean">.
```

That line is what makes the gate cheap: it turns "is this branch current?" from an
investigation into a read.

## Pitfalls

- **Syncing dirty.** The single most expensive mistake here.
- **Resolving a branch's conflicts inside the target.** It scales one bad call to every branch.
- **Treating a clean auto-merge as evidence.** Git checks that text does not collide, not
  that behaviour still holds.
- **Hand-resolving a generated region.**
- **Letting a deferral become permanent.** A branch that has skipped three syncs is not
  syncing, it is planning a rewrite. Say so out loud.
- **Assuming the remote is where you last saw it.** Other people and other agents push
  mid-session; fetch before deciding anything.
- **Forgetting to re-run the evidence** after a sync that touched it.

## Verification

- `git rev-list --left-right --count <target>...HEAD` reads `0` on the left.
- The tree is clean and the branch's own verification passes *after* the sync, not just
  before it.
- The sync is recorded with its sha.
