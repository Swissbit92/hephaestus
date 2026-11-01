"""The dev-based release route is one route, stated once and enforced by `--prepare`.

Before this, three places described how a release reaches `main` and they disagreed: the
`release.sh` PR-route text said to branch from "wherever you are" and to bump `plugin.json`
by hand, although the script already knows how to bump; `.crucible/release.json` declared
`from: dev` that nothing but the post-release fast-forward read; and CLAUDE.md / CONTRIBUTING.md
described neither. A hand-edit of the manifest is also exactly how a "bumped but untagged"
state arises.

The canonical route (cut the branch off `dev`, `--prepare`, PR into `main`, MERGE COMMIT,
re-run on `main` to tag) is asserted here at the three places a reader meets it. The behaviour
test drives the real script in a throwaway repo: a test that re-implemented `--prepare` would
only prove two copies agree.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from test_release_notes import BASH, RELEASE_SH, _git, repo  # noqa: F401  (repo is a fixture)

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(BASH is None, reason="no bash that actually runs")


def _pending(milestone: str):
    """TEMPORARY, removed milestone by milestone: strict, so a case that passes early fails."""
    return pytest.mark.xfail(strict=True, reason=f"lands in {milestone}")


def _run(repo_dir: Path, *args: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run([BASH, "scripts/release.sh", *args], cwd=str(repo_dir),
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=300)


def _out(proc: "subprocess.CompletedProcess[str]") -> str:
    return proc.stdout + proc.stderr


@pytest.fixture
def release_branch(repo):  # noqa: F811
    """`repo` with a `dev` level with main and `release/alpha-v0.2.0` cut off it."""
    _git(repo, "branch", "dev")
    _git(repo, "switch", "-c", "release/alpha-v0.2.0", "dev")
    # release.sh commits with plain `git commit`; give it an identity that does not depend on
    # the machine's global config (CI runners have none).
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def _tags(repo_dir: Path) -> list:
    return subprocess.run(["git", "tag", "--list", "alpha-v*"], cwd=str(repo_dir),
                          capture_output=True, text=True, encoding="utf-8").stdout.split()


# ------------------------------------------------------------ (a) --prepare behaviour
def test_prepare_makes_one_release_commit_and_nothing_else(release_branch):
    proc = _run(release_branch, "alpha", "0.2.0", "--prepare")
    assert proc.returncode == 0, _out(proc)

    count = subprocess.run(["git", "rev-list", "--count", "dev..HEAD"], cwd=str(release_branch),
                           capture_output=True, text=True, encoding="utf-8").stdout.strip()
    assert count == "1", "exactly one commit: the bump and the changelog cut together"

    manifest = release_branch / "plugins" / "alpha" / ".claude-plugin" / "plugin.json"
    assert json.loads(manifest.read_text(encoding="utf-8"))["version"] == "0.2.0"
    assert "## [alpha-v0.2.0]" in (release_branch / "CHANGELOG.md").read_text(encoding="utf-8")
    assert _tags(release_branch) == ["alpha-v0.1.0"], "--prepare must never tag"
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(release_branch),
                            capture_output=True, text=True, encoding="utf-8").stdout
    assert status == "", "the tree is left clean"


def test_prepare_refuses_main(repo):
    _git(repo, "branch", "dev")
    proc = _run(repo, "alpha", "0.2.0", "--prepare")
    assert proc.returncode != 0
    assert "--prepare" in _out(proc), "the refusal must name --prepare, not the generic main rule"


def test_prepare_refuses_dev_itself_and_a_detached_head(repo):
    """dev trivially contains dev, so only an explicit guard keeps the release commit off it."""
    _git(repo, "branch", "dev")
    _git(repo, "switch", "dev")
    proc = _run(repo, "alpha", "0.2.0", "--prepare")
    assert proc.returncode != 0 and "--prepare" in _out(proc)
    assert _tags(repo) == ["alpha-v0.1.0"]
    count = subprocess.run(["git", "rev-list", "--count", "main..dev"], cwd=str(repo),
                           capture_output=True, text=True, encoding="utf-8").stdout.strip()
    assert count == "0", "no release commit may land on dev"

    _git(repo, "switch", "--detach", "dev")
    proc = _run(repo, "alpha", "0.2.0", "--prepare")
    assert proc.returncode != 0 and "--prepare" in _out(proc)


def test_prepare_refuses_a_branch_that_does_not_contain_dev(repo):
    _git(repo, "branch", "dev")
    # dev moves on after the release branch was cut, so the branch no longer contains it.
    _git(repo, "switch", "-c", "release/alpha-v0.2.0")
    _git(repo, "switch", "dev")
    (repo / "later.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "later work on dev")
    _git(repo, "switch", "release/alpha-v0.2.0")
    proc = _run(repo, "alpha", "0.2.0", "--prepare")
    assert proc.returncode != 0
    out = _out(proc)
    assert "--prepare" in out and "dev" in out
    assert _tags(repo) == ["alpha-v0.1.0"]


def test_prepare_and_dry_run_are_mutually_exclusive(release_branch):
    proc = _run(release_branch, "alpha", "0.2.0", "--prepare", "--dry-run")
    assert proc.returncode != 0
    assert "--prepare" in _out(proc) and "--dry-run" in _out(proc)


def test_an_unknown_flag_is_rejected_not_ignored(release_branch):
    proc = _run(release_branch, "alpha", "0.2.0", "--prepar")
    assert proc.returncode != 0
    assert "--prepar" in _out(proc)


def test_prepare_with_an_unchanged_version_is_refused(release_branch):
    """Nothing to commit means nothing to prepare; say so instead of making an empty commit."""
    proc = _run(release_branch, "alpha", "0.1.0", "--prepare")
    assert proc.returncode != 0
    assert "--prepare" in _out(proc)


# ------------------------------------------------- (b) one route, stated in three places
def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_release_sh_pr_route_uses_prepare_not_a_hand_edit():
    src = RELEASE_SH.read_text(encoding="utf-8")
    route = src[src.index("PR route"):src.index("# --- Release gates")]
    assert "--prepare" in route
    assert "by hand" not in route
    assert "--base main" in route
    assert "squash" in route.lower(), "the route must say not to squash the release PR"


@pytest.mark.parametrize("doc", ["CLAUDE.md", "CONTRIBUTING.md"])
def test_docs_state_the_canonical_route(doc):
    text = _read(doc)
    assert "--prepare" in text, f"{doc} does not mention release.sh --prepare"
    assert re.search(r"merge commit", text, re.I), f"{doc} does not say to use a merge commit"
    assert re.search(r"never (a )?squash", text, re.I), f"{doc} does not forbid squashing the promotion"
    assert re.search(r"release/[^\n]{0,80}\boff\b[^\n]{0,6}dev", text, re.I), \
        f"{doc} does not say the release branch is cut off dev"


def test_release_json_declares_the_prepare_command():
    decl = json.loads(_read(".crucible/release.json"))
    assert decl["from"] == "dev" and decl["to"] == "main"
    assert "--prepare" in decl.get("prepare", []), "release.json has no prepare command"
    assert "--prepare" in RELEASE_SH.read_text(encoding="utf-8")


# ----------------------------------------------- (c) finish-branch, template, develop link
def test_finish_branch_states_the_pr_base_and_points_at_its_review_reference():
    skill = _read("plugins/crucible/skills/finish-branch/SKILL.md")
    assert "gh pr create" in skill and "--base" in skill
    ref = REPO_ROOT / "plugins" / "crucible" / "skills" / "finish-branch" / "references" / "pr-review.md"
    assert ref.is_file(), "the PR-review reference is missing"
    assert "references/pr-review.md" in skill, "SKILL.md does not point at its review reference"


def test_pull_request_template_has_disclosure_and_verification_sections():
    tpl = REPO_ROOT / ".github" / "pull_request_template.md"
    assert tpl.is_file(), "no pull request template"
    text = tpl.read_text(encoding="utf-8")
    assert re.search(r"^#+\s*Verification", text, re.M | re.I)
    assert re.search(r"^#+\s*AI", text, re.M | re.I)


def test_develop_phase_6_5_points_at_finish_branch_promote_phase():
    develop = _read("plugins/crucible/commands/develop.md")
    section = develop[develop.index("PHASE 6.5"):]
    assert re.search(r"finish-branch.{0,80}Phase 5|Phase 5.{0,80}finish-branch", section, re.S)
