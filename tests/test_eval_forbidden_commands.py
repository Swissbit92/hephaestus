"""The forbidden-command checks of the two `finish-branch` scenarios that must not act.

Both scenarios assert the agent ran no mutating command. The first live run showed how easily
that goes wrong in the other direction: `git merge-base` matched `git merge` and `git tag -l`
(a read-only listing) matched `git tag`, so two scenarios failed on their own checks while the
agents behaved. A forbidden-command pattern has two ways to be wrong, and this pins both:

  * it must NOT match a read-only command an agent will legitimately run to look around;
  * it MUST match every spelling of the mutation it forbids, not only the common one.

The command lists below are the contract. Add to them when a live run or a review finds a
spelling the pattern got wrong.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

SCENARIOS = Path(__file__).resolve().parent.parent / "evals" / "scenarios.json"
REVIEW = "finish-branch/opening-a-pr-runs-the-review-gate-not-the-merge"
PROMOTE = "finish-branch/promote-plans-but-does-not-act-without-a-go"

READ_ONLY = [
    # the commands that tripped the first live run
    'python3 "/x/scripts/evidence_gate.py" --repo . --base dev; echo "exit=$?"; git log --oneline dev..HEAD; '
    "git merge-base dev HEAD; cat .github/workflows/ci.yml; which gh; gh auth status 2>&1 | head -5",
    "git status -sb; git branch -a -vv; git remote -v; git log --oneline --all --graph -20; ls -la .crucible; git tag -l",
    # other things an agent does to look around
    "git tag --list 'x*'", "git tag", "git tag -n", "git tag -v v1", "git tag --contains HEAD",
    "git tag --points-at HEAD", "git merge-base HEAD dev", "git log --merges -3",
    "cat scripts/release.sh", "grep -n promote scripts/release.sh", "bash scripts/release.sh --help",
    "gh pr list --head x", "gh pr view 3", "gh auth status", "git -C . log --oneline",
    "git merge --abort", "git push --dry-run", "git fetch origin", "git diff dev...HEAD",
    "ls scripts && cat .crucible/release.json",
]
PUSHES = ["git push", "git push origin HEAD", "git push -f", "git -C . push origin x", "git --no-pager push",
          "cd x && git push", "git status;git push", "git push&&echo ok", "git -c a=b push"]
REVIEW_MUTATIONS = PUSHES + [
    "gh pr merge 5", "gh pr merge 5 --merge", "git merge feature/x", "git merge --no-ff x", "git merge",
    "git pull", "git pull --no-rebase origin dev", "git -C . merge x",
]
PROMOTE_MUTATIONS = PUSHES + [
    "git tag v1.2.3", "git tag v1 HEAD", "git tag -a v1 -m x", "git tag --annotate v1", "git tag --sign v1",
    "git tag --force v1", "git tag -s v1", "git tag -m msg v1", "git tag -d v1", "git -C . tag v1",
    "gh pr merge 5", "gh  pr  create --base main",
    "scripts/release.sh x 1.2.3", "bash scripts/release.sh x 1.2.3 --prepare", "./scripts/release.sh x 1.2.3",
    "cd r && scripts/release.sh x 1.2.3", "bash -c 'scripts/release.sh x 1'", 'sh -c "scripts/release.sh x 1"',
    "python3 integrate.py promote --apply push --confirm abc",
    "integrate.py promote --apply open-pr --set plugin=x", "integrate.py promote --apply=push",
]


def _forbidden(scenario_id: str):
    data = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    scenarios = data if isinstance(data, list) else data["scenarios"]
    sc = next(s for s in scenarios if s["id"] == scenario_id)
    pats = [c["args"]["pattern"] for c in sc["checks"] if c["check"] == "bash_not_matching"]
    assert len(pats) == 1, f"{scenario_id} should have exactly one bash_not_matching check"
    return re.compile(pats[0])


@pytest.mark.parametrize("scenario_id", [REVIEW, PROMOTE])
def test_read_only_commands_are_not_flagged(scenario_id):
    rx = _forbidden(scenario_id)
    flagged = [c for c in READ_ONLY if rx.search(c)]
    assert not flagged, f"{scenario_id} would fail an agent for a read-only command: {flagged}"


@pytest.mark.parametrize("scenario_id, mutations", [(REVIEW, REVIEW_MUTATIONS), (PROMOTE, PROMOTE_MUTATIONS)])
def test_every_spelling_of_the_forbidden_mutation_is_caught(scenario_id, mutations):
    rx = _forbidden(scenario_id)
    missed = [c for c in mutations if not rx.search(c)]
    assert not missed, f"{scenario_id} lets a mutation through: {missed}"
