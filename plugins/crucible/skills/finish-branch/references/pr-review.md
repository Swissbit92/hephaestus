# The PR review gate

Loaded when `finish-branch` opens a pull request. `SKILL.md` carries the rule; this is how to
run it and why it takes this shape.

## The rule

A PR is merged only when **both** hold, read fresh at merge time:

1. **No unresolved high-severity finding** from the review pass below.
2. **The target's required checks are green** on the PR's head commit.

Either one missing is *not met*, not "probably fine". If the review could not run (no reviewer
available, the diff could not be read) or the checks could not be read, that is *could not
determine* — say so and stop; never fold it into a pass.

## Running the review

1. Open the PR first: `gh pr create --base <target> --head <branch>` (title and body from the
   branch's commits and the repo's PR template, if it has one). With no `gh` or no remote, say
   so and give the user the branch to open by hand — the gate still applies.
2. Review the PR's own diff, `git diff <target>...<branch>`, with `qa-gatekeeper` or any other
   code-review pass the environment offers. Do not name a tool the host may not have.
3. Post the findings on the PR (`gh pr comment`, or inline review comments where the host
   supports them) so the record outlives the session. Rank by severity.
4. **High** means a correctness bug, a security hole, data loss, or a gate bypassed or
   weakened. Everything else is advisory: reported, never blocking.
5. A finding is *resolved* when it was fixed and the fix re-reviewed, or the user dismissed it
   with a reason written on the PR. The agent never dismisses a high-severity finding itself.

## Applies to every path

The gate runs for any branch that reaches `finish-branch`, including work that never went
through `develop` — a hotfix or a manual branch has had no milestone review, so this is the
only independent look it gets.

## Why a check and a comment, not an approval count

GitHub does not let an author approve their own pull request, so on a solo-maintained repo a
required-approvals rule either locks the maintainer out or trains them to bypass it. A required
status check can be satisfied by the review pass; the written findings and the user's explicit
go are the human part. Block only at high severity: a gate that stops on style teaches people
to dismiss it, and a dismissed gate is worse than none.

Merge with the method the repo's branch model names (in its contributor docs). Where a release
PR promotes an integration branch into a deploy branch, use a merge commit rather than a squash,
or the two branches drift apart.
