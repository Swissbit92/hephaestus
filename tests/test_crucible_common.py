"""Tests for the helpers the crucible gate scripts share (crucible_common.py).

The one behaviour worth pinning: the branch point is taken from the integration target
start-branch recorded, not re-guessed. Before this module, only prose read that record —
every script re-ran the name heuristic, which in a repo with both `dev` and `main` can
pick the branch the work did NOT fork from, and then compares against the wrong baseline
while looking healthy.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import crucible_common as cc


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "dev")
    _git(repo, "switch", "-q", "-c", "feature/x")
    return repo


def test_the_heuristic_picks_dev_when_nothing_is_recorded(tmp_path):
    assert cc.detect_target(_repo(tmp_path)) == "dev"


def test_the_recorded_integration_target_wins_over_the_heuristic(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "config", "branch.feature/x.integrationTarget", "main")
    assert cc.detect_target(repo) == "main"


def test_a_recorded_target_that_no_longer_exists_falls_back(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "config", "branch.feature/x.integrationTarget", "release")
    assert cc.detect_target(repo) == "dev"


def test_an_explicit_choice_beats_the_record(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "config", "branch.feature/x.integrationTarget", "main")
    assert cc.detect_target(repo, preferred="dev") == "dev"


def test_detached_head_has_no_branch(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "--detach")
    assert cc.current_branch(repo) is None and cc.recorded_target(repo) is None
