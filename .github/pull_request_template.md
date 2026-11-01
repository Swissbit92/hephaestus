## What and why

<!-- One or two sentences: what changes, and the reason. Link the issue or ADR if there is one. -->

## AI assistance

<!-- Tick one. Reviewers calibrate their attention to this; it is not a penalty. -->

- [ ] No AI tool was used for this change
- [ ] Partly AI-assisted — a person wrote or rewrote the parts that matter
- [ ] Largely AI-authored — a person has read every changed line

Tool / model used:
Reviewed by (a person):

## Verification

<!-- Evidence, not assertion: the command you ran and what it printed. Paste it. -->

- [ ] `pytest -q` — result:
- [ ] `scripts/check-public-safe.sh` is clean
- [ ] Required CI checks are green on this PR's head commit — link:
- [ ] If a skill's behavior changed: its eval scenario was added or updated (`evals/scenarios.json`)

## Review findings

<!-- finish-branch posts the review here. Merge only with no unresolved high-severity finding. -->

- [ ] Review pass run on this PR's diff, findings posted on the PR
- [ ] No unresolved high-severity finding (or each is dismissed with a written reason)

## Release PRs only

- [ ] Branch was cut off `dev` and prepared with `scripts/release.sh <plugin> <bump> --prepare`
- [ ] Merge with a **merge commit**, never a squash
