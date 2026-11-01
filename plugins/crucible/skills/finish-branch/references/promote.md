# `integrate.py promote --apply` — the release route, one step at a time

Loaded when `finish-branch` Phase 5 runs in a repo that declares `.crucible/release.json`.
`SKILL.md` carries the rule; this is the reference and the reasons.

## The commands

```bash
integrate.py promote --set plugin=<p> --set version=<x.y.z>                 # the plan: read-only
integrate.py promote --apply branch   --set plugin=<p> --set version=<x.y.z>   # local
integrate.py promote --apply prepare  --set plugin=<p> --set version=<x.y.z>   # local
integrate.py promote --apply push     --set … --confirm <plan id>              # external
integrate.py promote --apply open-pr  --set … --confirm <plan id>              # external
```

`promote` alone never acts. It prints the release branch (`release/<plugin>-v<version>`), **every
command `--confirm` can make the script run, in full** (`push`, `open_pr`, `pr_view`), and a
`plan: <id>`. Show the user that plan; that is what they are approving.

## What each step does, and refuses

| Step | Runs | Refuses when | Already done when |
|---|---|---|---|
| `branch` | `git switch -c <branch> <from>` | tree dirty; local `from` ≠ `origin/from` (after a fetch); the branch exists but lacks `from` | the branch exists and contains `from` |
| `prepare` | the declared `prepare` argv | not on the branch; dirty; branch does not contain `from`; it is already >1 commit ahead | the branch is exactly one commit ahead |
| `push` | `git push -u origin refs/heads/<b>:refs/heads/<b>` | the branch is missing or not exactly one prepared commit; `origin/<b>` is not an ancestor (never forces) | `origin/<b>` is at the local tip |
| `open-pr` | the declared `open_pr` argv | the branch is not on origin at its tip | `pr_view` already finds a PR |

`prepare` must leave exactly one new commit **on that branch** and a clean tree; the script re-reads
HEAD and the branch tip afterwards. Neither local step needs `--confirm`, and `prepare` runs the
declared argv — in this repo `scripts/release.sh`, which a merged PR can edit. "Local, reversible"
describes what the shipped `release.sh` does, not something the script can enforce for an arbitrary
argv: the plan prints that argv in full and is the only review point before it runs. Every step reads state, acts, then reads state again — a
success is a fresh read, never an exit code (`act-for-real`).

## The plan id is a staleness guard, not authorization

It is a hash of the facts a step acts on (the `from`/`to` shas and their `origin/` shas, the branch
and its tip, the version, every declared argv). `push` and `open-pr` recompute it from the current refs
(local branches and the remote-tracking refs as of the last fetch — `branch` fetches; `push` re-reads
origin with `ls-remote` before and after); a mismatch is **exit 4** with both ids shown. Anyone can compute it, including the agent, so
it does not prove the user agreed to anything. The authorization is the user's go, in the
conversation, for **that exact action** ("push `release/x-v1.2.3` to origin"); a go for one plan is
never spent on another, and an earlier "go ahead" is not a go. Because the id covers the branch
tip, re-run `promote` after `prepare` and show the new plan before asking for the push.

## `open_pr` and `pr_view` (no forge is assumed)

Both are argv lists in the declaration, with `{branch}`, `{from}`, `{to}`, `{plugin}`, `{version}`
placeholders. Without `open_pr` the step is a SKIP (exit 3) that prints what to do by hand; without
`pr_view` it is a SKIP too, because it could be neither idempotent nor verified.

`pr_view` contract: **exit 0 and print something = a PR exists; exit 0 and print nothing = none;
any non-zero exit = could not determine (exit 2).** An error must never read as "no PR", or a failed
lookup opens a duplicate. Key it on the head branch (`{branch}`), so a different PR cannot satisfy it.
For GitHub: `gh pr list --head {branch} --base {to} --state open --json url --jq '.[0].url // empty'`
(`gh pr view` exits 1 both for "none" and for failures, which is why it is not used).
`--state open` means the lookup sees only an open PR: once it is merged or closed, `open-pr` would try
again, so run it before the merge. This repo's `open_pr` passes `--body-file
.github/pull_request_template.md`, so the release PR carries the review-gate checklist (`--fill`
would fill the body from the commits and ignore the template).

## What is deliberately not here

No `merge`, no `tag`, no `release`/`publish` step, no `--yes`, no auto-confirm, no force-push, no
polling CI, no default forge. Merging is the single human gate (the same split release-please and
changesets draw: the tool prepares a reviewable PR; the merge is the human's). Tagging and
publishing are `release.sh` on the target branch — irreversible, and its own explicit go.

## Notes

- `push -u` sets the upstream of the release branch in the local config; nothing else.
- Reads (`ls-remote`) use the fetch URL and the push uses the push URL; with a split
  `pushurl`/`insteadOf` setup they can name different repositories.
- Exit codes: `0` done or already done · `1` refused or failed · `2` could not determine (missing
  `--confirm`, a lookup that errored, a result that could not be read back) · `3` nothing declared ·
  `4` stale plan.
