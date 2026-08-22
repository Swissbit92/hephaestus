---
name: start-branch
description: Isolate work on its own branch or worktree before implementing — detects the repo's integration target (never hardcoded), picks a plain branch vs. git worktree, names it Conventional-Branch style, records a clean test baseline, and confirms in one line. Use before starting non-trivial implementation, or when the develop workflow reaches its ISOLATE phase.
---

You set up an isolated workspace so changes never land uncommitted on a shared or
deploy branch. You **detect** the repo's conventions — you never assume them. You do
not implement and you do not merge; that is for later phases.

## Phase 1 — Detect the branch model (never hardcode)

Find the integration target by reading the repo, in this order:

1. The repo's `CLAUDE.md`, then `CONTRIBUTING.md` — look for a declared branch model
   and integration branch.
2. If nothing is declared, infer from git: `git branch -r` and the long-lived branch
   names present (`main`, `master`, `dev`, `develop`, `prod`, `trunk`).

Classify into one of the common models and name the integration target:
- **two-branch** (`dev` integrates, `prod`/`main` deploys) → target `dev`
- **main-release** (`main` integrates and releases) → target `main`
- **trunk-based** (everything off `main`) → target `main`
- **GitHub-Flow** (feature branches → `main` via PR) → target `main`

If the model is genuinely ambiguous, **ask once** — present your best guess and let the
user confirm or correct. Don't guess silently.

**Then record the answer, once the branch exists (Phase 5):**

```bash
git config branch.<branch>.integrationTarget <target>
```

Detection is a heuristic and the user's correction is the only authoritative part of it,
yet it is the part that evaporates: `finish-branch` and `qa-gatekeeper` re-derive the
target later, from the same heuristic, in a session that may not be this one. In an
ambiguous repo they can land on a different branch than the one you actually forked
from — and then the gate compares against the wrong baseline while looking entirely
healthy. Writing it into git config makes the answer outlive the conversation.

It goes in `.git/config` deliberately: that file is per-clone, never committed and never
merged. Recording it in a tracked file instead would put branch bookkeeping into the
branch's own diff, where it causes conflicts between parallel branches and ends up in
the merge.

## Phase 2 — Choose the isolation primitive

Default to a **plain branch** (`git switch -c <name>`).

Choose a **git worktree** only when the work is: run in parallel with other work, risky/
experimental (you may want to throw it away cleanly), or it touches deploy-triggering
paths you'd rather keep off the main checkout. Use the harness `EnterWorktree` tool if
available, else `git worktree add`.

⚠️ A worktree starts **fresh**: no uncommitted files, no `.env*`, no `node_modules`,
no build artifacts. Say so before creating one, so the user isn't surprised by a missing
local setup.

⚠️ **A worktree isolates the source tree and the index — nothing else.** Everything the
repo shares with the machine is still shared: the dev-server port, the local database,
the build output directory, deployed artifacts, a running editor's daemon. Parallel
*editing and building* is safe; anything that deploys, migrates, renders to a fixed path
or mutates a shared service must be **serialised — one worktree at a time**. This is the
failure that looks like a bug in the code rather than a bug in the setup, because both
worktrees are individually correct.

Two mechanics worth stating before they bite:

- **One branch can be checked out in only one worktree.** That is why parallel work forks
  a *new* branch instead of checking the existing one out again.
- **Never name a child `<parent>/<slug>` when `<parent>` is itself a ref.** Git stores
  `feature/api` as a file, so it cannot also create the `feature/api/` directory that
  `feature/api/auth` needs, and `git worktree add` fails with a refname error that reads
  as corruption. Use a hyphen: `feature/api-auth`.

## Phase 3 — Name the branch (Conventional Branch)

`<type>/<short-description>` in kebab-case:
- `feature/` · `bugfix/` · `hotfix/` · `chore/`
- Prefix with a ticket id when there is one (`feature/PROJ-123-short-desc`).

Keep it short and descriptive. (The `claude/` AI-source prefix exists but is not the
default — only use it if the repo asks for it.)

## Phase 4 — Establish the test baseline

Run the repo's test command and record pass/fail + count **at this commit** — a live
snapshot of ground truth at the branch point. Downstream gates re-derive from this point
rather than trusting the number, so record what the tree actually shows. This baseline is
the gate `finish-branch` enforces.

If the baseline is already **red**, say so explicitly — `finish-branch` requires green to
merge, not merely "no worse than a failing baseline." The user should know they're
starting from a broken tree before they build on it.

## Phase 5 — Confirm, then act

**First, re-check that the target has not moved.** Phase 1 found the integration target;
minutes or hours of research may have passed since, and a local ref is only as fresh as
the last fetch:

```bash
git fetch origin --quiet
git rev-list --count <target>..origin/<target>   # 0 = current
```

Branch from `origin/<target>`, not the local ref, whenever they differ — and say so, with
the count, rather than silently taking the newer one. If the local ref is behind, the
Phase 4 baseline was measured on the wrong tree and must be re-taken after branching.

This is not the same problem as recording the target in git config, which fixes *recovery*
— knowing where to merge back. This fixes *staleness* — starting from what is actually
there. A base that was current when you looked is not current when you branch, and nothing
about the branch will look wrong afterwards: it is a normal branch off a real commit, and
the work you duplicate was work that already merged.

Then propose the whole plan in one line and wait for confirmation before creating anything:

> Isolate on `feature/short-access-token` (plain branch) · integrate to `dev` (origin/dev, 0 behind) · baseline: 142 tests passing — proceed?

On confirm, create the branch/worktree and hand off to implementation.

## Guardrails

- **Never start from a dirty tree silently.** If there are uncommitted changes, surface
  them and ask whether to bring them along, stash, or commit first.
- **Never deploy as a side effect.** Creating a branch must not push or trigger CI/CD.
- **Never implement or merge here.** This skill only isolates. Stop after the branch
  exists.
- **Detect, don't assume.** If you find yourself hardcoding `main` or `dev`, stop and
  read the repo instead.
- **Never branch from a ref you have not fetched in this phase.** Detection and creation
  are separated by however long the work in between took, and a stale base fails silently:
  you rebuild what already landed, and the merge is clean because the commits are real.
