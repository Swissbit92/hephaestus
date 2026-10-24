"""Tests for integrate.py — integration advice and the declared promote path.

Two properties matter. CI is read from the TARGET's tree (a branch that adds a workflow
proves nothing about the branch it merges into). And nothing here performs the
irreversible step: `promote` plans and dry-runs; the release command is never executed.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugins" / "crucible" / "scripts" / "integrate.py"

sys.path.insert(0, str(REPO_ROOT / "evals"))
import fixtures  # noqa: E402

import crucible_common as cc  # noqa: E402


def _run(repo, *args):
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=120)
    return r.returncode, r.stdout + r.stderr


# --------------------------------------------------------------------------- recommend
def test_ci_on_the_target_recommends_a_pr(tmp_path):
    repo = fixtures.build("finish_green_ci", tmp_path / "r")
    code, out = _run(repo, "recommend", "--offline")
    assert code == 0 and out.startswith("RECOMMEND: pr") and "github-actions" in out


def test_no_ci_leaves_the_choice_open(tmp_path):
    repo = fixtures.build("finish_green_remote", tmp_path / "r")
    code, out = _run(repo, "recommend", "--offline")
    assert code == 0 and out.startswith("RECOMMEND: choose") and "no CI" in out


def test_no_remote_means_no_pr_is_possible(tmp_path):
    repo = fixtures.build("finish_green", tmp_path / "r")
    code, out = _run(repo, "recommend", "--offline")
    assert code == 0 and "not possible" in out


def test_a_workflow_added_only_on_the_branch_does_not_count(tmp_path):
    """The branch adds CI; the target has none. Recommending a PR here would credit the
    target with checks it does not run."""
    repo = fixtures.build("finish_green_remote", tmp_path / "r")
    fixtures._write(repo, ".github/workflows/ci.yml", fixtures._CI_WORKFLOW)
    fixtures._commit_all(repo, "branch adds CI")
    code, out = _run(repo, "recommend", "--offline")
    assert code == 0 and out.startswith("RECOMMEND: choose")


def test_detect_ci_names_each_host_and_reads_a_given_ref(tmp_path):
    repo = fixtures.branched_repo(tmp_path / "r", {".gitlab-ci.yml": "x\n", "Jenkinsfile": "x\n",
                                                   ".github/workflows/a.yaml": "x\n", "README.md": "x\n"})
    assert cc.detect_ci(repo, "dev") == ["github-actions", "gitlab-ci", "jenkins"]
    assert cc.detect_ci(repo, "no-such-ref") is None


# --------------------------------------------------------------------------- promote
def _declare(repo: Path, decl) -> None:
    fixtures._write(repo, ".crucible/release.json", decl if isinstance(decl, str) else json.dumps(decl))


def test_promote_prints_the_declared_path_and_never_runs_the_release(tmp_path):
    repo = fixtures.branched_repo(tmp_path / "r", {"README.md": "x\n"})
    sentinel = tmp_path / "RELEASED"
    _declare(repo, {"from": "dev", "to": "main", "via": "pr",
                    "command": [sys.executable, "-c", f"open({str(sentinel)!r}, 'w')", "{version}"],
                    "dry_run": [sys.executable, "-c", "print('would release {version}')"]})
    code, out = _run(repo, "promote", "--set", "version=1.2.3")
    assert code == 0 and "dev -> main via pr" in out and "would release 1.2.3" in out
    assert "explicit go" in out
    assert not sentinel.exists(), "promote must never run the release command"


def test_a_failing_dry_run_fails_the_plan(tmp_path):
    repo = fixtures.branched_repo(tmp_path / "r", {"README.md": "x\n"})
    _declare(repo, {"from": "dev", "to": "main", "dry_run": [sys.executable, "-c", "raise SystemExit(4)"]})
    code, out = _run(repo, "promote")
    assert code == 1 and "exit 4" in out


def test_a_missing_placeholder_is_undetermined(tmp_path):
    repo = fixtures.branched_repo(tmp_path / "r", {"README.md": "x\n"})
    _declare(repo, {"from": "dev", "to": "main", "command": ["release", "{version}"]})
    code, out = _run(repo, "promote")
    assert code == 2 and "--set version=" in out


def test_a_malformed_declaration_is_undetermined(tmp_path):
    repo = fixtures.branched_repo(tmp_path / "r", {"README.md": "x\n"})
    _declare(repo, {"from": "dev", "to": "", "via": "rebase"})
    code, out = _run(repo, "promote")
    assert code == 2 and "'to'" in out and "'via'" in out


def test_an_undeclared_repo_is_a_skip_not_a_guess(tmp_path):
    repo = fixtures.branched_repo(tmp_path / "r", {"README.md": "x\n"})
    code, out = _run(repo, "promote")
    assert code == 3 and "declare the release path" in out and "SKIP" in out


def test_a_release_tool_means_the_promote_step_is_a_pr(tmp_path):
    repo = fixtures.branched_repo(tmp_path / "r", {"release-please-config.json": "{}\n"})
    code, out = _run(repo, "promote")
    assert code == 0 and "release-please" in out and "PR" in out


def test_this_repos_declaration_is_valid():
    """The repo dogfoods the contract: its own release path is declared and parses."""
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("integrate", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    decl = mod.load_declaration(REPO_ROOT)
    assert decl["from"] == "dev" and decl["to"] == "main" and decl["via"] == "pr"
