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
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from test_release_notes import BASH, RELEASE_SH, _commit, _git, repo  # noqa: F401  (repo is a fixture)

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(BASH is None, reason="no bash that actually runs")


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


def test_prepare_refuses_dev_itself(repo):
    """dev trivially contains dev, so only an explicit guard keeps the release commit off it."""
    _git(repo, "branch", "dev")
    _git(repo, "switch", "dev")
    proc = _run(repo, "alpha", "0.2.0", "--prepare")
    assert proc.returncode != 0 and "--prepare" in _out(proc)
    assert _tags(repo) == ["alpha-v0.1.0"]
    count = subprocess.run(["git", "rev-list", "--count", "main..dev"], cwd=str(repo),
                           capture_output=True, text=True, encoding="utf-8").stdout.strip()
    assert count == "0", "no release commit may land on dev"


def test_prepare_refuses_a_detached_head(repo):
    """A release commit on a detached HEAD belongs to no branch and is lost on the next switch."""
    _git(repo, "branch", "dev")
    _git(repo, "switch", "--detach", "dev")
    proc = _run(repo, "alpha", "0.2.0", "--prepare")
    assert proc.returncode != 0 and "--prepare" in _out(proc)
    assert _tags(repo) == ["alpha-v0.1.0"]


def test_prepare_needs_a_local_dev_to_check_against(repo):
    """With no local `dev` there is nothing to prove the branch contains; say how to get one."""
    _git(repo, "switch", "-c", "release/alpha-v0.2.0")
    proc = _run(repo, "alpha", "0.2.0", "--prepare")
    assert proc.returncode != 0
    assert "needs a local 'dev'" in _out(proc) and "git fetch origin dev:dev" in _out(proc)
    assert _tags(repo) == ["alpha-v0.1.0"]


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
    assert "git fetch --unshallow" in out, "a shallow clone fails this check for lack of history"
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
    assert "already at 0.1.0" in _out(proc), "the refusal must say why, not just name the flag"
    assert "no release commit to make" in _out(proc)


# ------------------------------------------------- (b) one route, stated in three places
def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


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


# ------------------------------------------- PR-review findings: stale dev, quiet level-up
# A real release run needs its gates and `gh`; the fixture stubs them so the run reaches the
# part under test (the push and the level-up of dev) instead of dying at a gate.
_POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32",
                                 reason="stubs `gh` on PATH with a shell script")


@pytest.fixture
def world(repo, tmp_path):  # noqa: F811
    """`repo` + passing gate stubs + a bare origin carrying main and dev."""
    _commit(repo, "scripts/check-public-safe.sh", "#!/bin/sh\nexit 0\n", "stub: public-safe gate")
    _commit(repo, "scripts/validate_manifests.py", "raise SystemExit(0)\n", "stub: manifest gate")
    _commit(repo, "tests/test_ok.py", "def test_ok():\n    assert True\n", "stub: a passing test")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(origin)], check=True,
                   capture_output=True)
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "branch", "dev")
    _git(repo, "push", "-q", "origin", "main", "dev")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def _run_real(repo_dir: Path, tmp_path: Path, *args: str,
              gh_body: str = "exit 0") -> "subprocess.CompletedProcess[str]":
    """release.sh with `gh` stubbed (a no-op unless `gh_body` says otherwise) and the
    interpreter that has pytest."""
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    gh = stub / "gh"
    gh.write_text(f"#!/bin/sh\n{gh_body}\n", encoding="utf-8")
    gh.chmod(0o755)
    env = dict(os.environ, PATH=str(stub) + os.pathsep + os.environ["PATH"], PYTHON=sys.executable)
    return subprocess.run([BASH, "scripts/release.sh", *args], cwd=str(repo_dir), env=env,
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=300)


def _rev(repo_dir: Path, ref: str) -> str:
    return subprocess.run(["git", "rev-parse", ref], cwd=str(repo_dir), capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


def _prepared_and_merged(world, tmp_path):
    """Cut a release branch off dev, --prepare it, merge it into main with a merge commit."""
    _git(world, "switch", "-c", "release/alpha-v0.2.0", "dev")
    proc = _run_real(world, tmp_path, "alpha", "0.2.0", "--prepare")
    assert proc.returncode == 0, _out(proc)
    _git(world, "switch", "main")
    _git(world, "merge", "--no-ff", "-q", "-m", "Merge release/alpha-v0.2.0", "release/alpha-v0.2.0")


@_POSIX_ONLY
def test_prepare_refuses_when_origin_dev_has_work_the_branch_lacks(world, tmp_path):
    """A local `dev` behind `origin/dev` passes the local ancestry check, and the release PR
    would then silently omit merged work."""
    _git(world, "switch", "-c", "release/alpha-v0.2.0", "dev")
    _git(world, "switch", "-c", "someone-elses-work", "dev")
    _commit(world, "later.txt", "x\n", "work merged to dev by someone else")
    _git(world, "push", "-q", "origin", "someone-elses-work:dev")
    _git(world, "switch", "release/alpha-v0.2.0")
    proc = _run_real(world, tmp_path, "alpha", "0.2.0", "--prepare")
    assert proc.returncode != 0
    out = _out(proc)
    assert "origin/dev" in out and "--prepare" in out
    assert _tags(world) == ["alpha-v0.1.0"]


@_POSIX_ONLY
def test_a_release_levels_dev_when_nothing_moved(world, tmp_path):
    _prepared_and_merged(world, tmp_path)
    proc = _run_real(world, tmp_path, "alpha", "0.2.0")
    assert proc.returncode == 0, _out(proc)
    assert "alpha-v0.2.0" in _tags(world)
    assert _rev(world, "dev") == _rev(world, "main"), "dev must be level with main afterwards"


@_POSIX_ONLY
def test_a_release_that_cannot_level_dev_says_so_and_fails(world, tmp_path):
    """dev moved after the release branch was cut, so main does not contain it. The release
    itself is published, but the integration branch is NOT levelled: that must be loud
    (non-zero, a WARNING) and not a note followed by a tick."""
    _prepared_and_merged(world, tmp_path)
    _git(world, "switch", "dev")
    _commit(world, "later.txt", "x\n", "dev moved after the release branch was cut")
    _git(world, "switch", "main")
    proc = _run_real(world, tmp_path, "alpha", "0.2.0")
    out = _out(proc)
    assert "alpha-v0.2.0" in _tags(world), "the release itself is still published"
    assert proc.returncode != 0, out
    assert "WARNING" in out and "dev" in out and "NOT levelled" in out
    assert _rev(world, "dev") != _rev(world, "main")


_PROTECTED_MAIN = ('if [ "$1" = api ]; then echo \'{"required_status_checks": {"contexts": ["checks"]}, '
                   '"enforce_admins": {"enabled": true}}\'; fi; exit 0')


@_POSIX_ONLY
def test_a_real_run_on_protected_main_prints_the_dev_based_route_and_changes_nothing(world, tmp_path):
    """The die text only fires when `main` requires checks and enforces them on admins. Drive
    it for real with a stubbed `gh api`, instead of reading the script's source."""
    before = _rev(world, "HEAD")
    proc = _run_real(world, tmp_path, "alpha", "0.2.0", gh_body=_PROTECTED_MAIN)
    out = _out(proc)
    assert proc.returncode != 0
    assert "git switch -c release/alpha-v0.2.0 dev" in out, "the branch is cut off dev, not main"
    assert "release.sh alpha 0.2.0 --prepare" in out
    assert "gh pr create --base main" in out
    assert "MERGE COMMIT" in out and "never squash" in out
    assert "by hand" not in out
    assert _rev(world, "HEAD") == before and _tags(world) == ["alpha-v0.1.0"]
    status = subprocess.run(["git", "status", "--porcelain"], cwd=str(world),
                            capture_output=True, text=True, encoding="utf-8").stdout
    assert status == "", "the refusal must leave the manifest and changelog untouched"
