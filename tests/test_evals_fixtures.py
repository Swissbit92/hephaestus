"""Headless tests for the live-side eval pieces that DON'T need claude: the git/file
snapshot (world.py), the fixture builders, and scenarios.json integrity. These use the real
git CLI (always present in this repo's environment)."""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

import pytest

import fixtures
from harness import scoring, world

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = REPO_ROOT / "evals" / "scenarios.json"


# --------------------------------------------------------------------------- world.snapshot
def test_snapshot_captures_branch_commits_branches(tmp_path):
    repo = fixtures.build("finish_green", tmp_path / "r")
    snap = world.snapshot(repo)
    assert snap.branch == "feature/add-feature"
    assert "add feature (green)" in snap.commits
    assert {"main", "dev", "feature/add-feature"} <= set(snap.branches)
    assert "CLAUDE.md" in snap.files and ".git" not in " ".join(snap.files)


def test_snapshot_detects_dirty(tmp_path):
    repo = fixtures.build("start_dirty", tmp_path / "r")
    snap = world.snapshot(repo)
    assert snap.dirty is True
    assert "wip.txt" in snap.files


# --------------------------------------------------------------------------- fixtures
def test_finish_red_on_feature_with_failing_test(tmp_path):
    repo = fixtures.build("finish_red", tmp_path / "r")
    assert (repo / "tests" / "test_feature.py").read_text(encoding="utf-8").count("== 3")  # failing
    assert world.snapshot(repo).branch == "feature/add-feature"


def test_finish_on_target_is_on_dev(tmp_path):
    repo = fixtures.build("finish_on_target", tmp_path / "r")
    assert world.snapshot(repo).branch == "dev"


def test_start_clean_on_main_not_dirty(tmp_path):
    repo = fixtures.build("start_clean", tmp_path / "r")
    s = world.snapshot(repo)
    assert s.branch == "main" and s.dirty is False


def test_second_brain_vault_has_inbox(tmp_path):
    repo = fixtures.build("second_brain_vault", tmp_path / "r")
    assert (repo / "Inbox" / "thought.md").exists()
    assert (repo / "_meta" / "tags.md").exists()


def test_cms_repo_has_valid_docs(tmp_path):
    repo = fixtures.build("cms_repo", tmp_path / "r")
    assert (repo / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8").startswith("---")


def test_sqlite_fixture_has_rows(tmp_path):
    repo = fixtures.build("sqlite_db", tmp_path / "r")
    con = sqlite3.connect(str(repo / "data.db"))
    assert con.execute("SELECT count(*) FROM employees").fetchone()[0] == 3
    con.close()


def test_all_fixtures_build(tmp_path):
    for i, name in enumerate(fixtures.FIXTURES):
        repo = fixtures.build(name, tmp_path / f"f{i}")
        assert (repo / ".git").exists()


def test_build_unknown_fixture_raises(tmp_path):
    with pytest.raises(KeyError):
        fixtures.build("nope", tmp_path / "x")


# --------------------------------------------------------------------------- Phase 5 fixtures
def _run_pytest(repo: Path) -> tuple[int, int]:
    """(passed, failed) for the fixture's own tiny suite."""
    import re as _re
    import subprocess
    out = subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", str(repo / "tests")],
                         capture_output=True, text=True, cwd=str(repo)).stdout
    passed = int(m.group(1)) if (m := _re.search(r"(\d+) passed", out)) else 0
    failed = int(m.group(1)) if (m := _re.search(r"(\d+) failed", out)) else 0
    return passed, failed


def test_qa_regression_defeats_count_only_comparison(tmp_path):
    """The whole point of this fixture: passing COUNT is unchanged vs. the branch point, yet
    a test that passed at BASE now fails. A gate comparing only counts cannot catch it."""
    repo = fixtures.build("qa_regression", tmp_path / "r")
    head_passed, head_failed = _run_pytest(repo)
    assert (head_passed, head_failed) == (3, 1), f"expected 3 passed/1 failed at HEAD, got {head_passed}/{head_failed}"

    base = tmp_path / "base"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(base), "dev"],
                   check=True, capture_output=True, text=True)
    base_passed, base_failed = _run_pytest(base)
    assert (base_passed, base_failed) == (3, 0), f"expected 3 passed/0 failed at BASE, got {base_passed}/{base_failed}"
    assert head_passed == base_passed          # counts agree — the trap
    assert head_failed > base_failed           # but a BASE-passing test now fails
    # and the branch really delivers its named feature, so REJECT can only be about the bug
    assert "def perimeter" in (repo / "widget.py").read_text(encoding="utf-8")


def test_qa_clean_is_a_complete_green_change(tmp_path):
    """Must deliver a real feature, not just an extra test — otherwise the gate rejects it
    for being an empty branch and the scenario measures the wrong thing."""
    repo = fixtures.build("qa_clean", tmp_path / "r")
    passed, failed = _run_pytest(repo)
    assert (passed, failed) == (3, 0)
    assert world.snapshot(repo).branch == "feature/add-perimeter"
    src = (repo / "widget.py").read_text(encoding="utf-8")
    assert "def perimeter" in src, "branch name promises a feature the diff must actually deliver"
    assert "def test_perimeter" in (repo / "tests" / "test_widget.py").read_text(encoding="utf-8")


def test_qa_deleted_tests_is_green_at_head_but_shrunken_vs_base(tmp_path):
    """HEAD alone looks perfect. Only a BASE comparison exposes the lost coverage — this is
    the fixture that makes ground-truth derivation load-bearing rather than optional."""
    repo = fixtures.build("qa_deleted_tests", tmp_path / "r")
    head_passed, head_failed = _run_pytest(repo)
    assert (head_passed, head_failed) == (2, 0), f"HEAD must look clean, got {head_passed}/{head_failed}"

    base = tmp_path / "base"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(base), "dev"],
                   check=True, capture_output=True, text=True)
    base_passed, base_failed = _run_pytest(base)
    assert (base_passed, base_failed) == (4, 0)
    assert head_failed == 0                    # nothing fails — the trap
    assert head_passed < base_passed           # yet coverage regressed 4 -> 2


def test_develop_full_declares_the_invariant_and_has_a_consumer(tmp_path):
    """The fixture must make the change genuinely blast-radius, or the scenario proves nothing."""
    repo = fixtures.build("develop_full", tmp_path / "r")
    claude = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert "public API" in claude and "schema.py" in claude
    assert "rsi_14" in (repo / "schema.py").read_text(encoding="utf-8")
    assert "from schema import COLUMNS" in (repo / "consumer.py").read_text(encoding="utf-8")
    assert world.snapshot(repo).branch == "dev"


def test_develop_trivial_has_the_typo_and_starts_on_dev(tmp_path):
    repo = fixtures.build("develop_trivial", tmp_path / "r")
    assert "recieve" in (repo / "README.md").read_text(encoding="utf-8")
    snap = world.snapshot(repo)
    assert snap.branch == "dev"
    assert snap.dirty is False


# --------------------------------------------------------------------------- scenarios.json integrity
def _load_scenarios():
    return json.loads(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]


def test_scenarios_file_loads_and_has_entries():
    scs = _load_scenarios()
    assert len(scs) >= 8


def test_forbidden_command_patterns_target_execution_not_mention():
    """A `bash_not_matching` guard must distinguish running a dangerous script from merely
    inspecting it. The act-for-real guard originally matched the bare filename, so a
    read-only `git diff migrate.sh` — good practice before a one-way action — failed the
    scenario while the migration itself had correctly never run."""
    import re
    scs = {s["id"]: s for s in _load_scenarios()}
    s = scs["act-for-real/refuses-irreversible-without-approval"]
    pat = next(c["args"]["pattern"] for c in s["checks"] if c["check"] == "bash_not_matching")
    rx = re.compile(pat)
    for cmd in ["./migrate.sh", "cd /srv && ./migrate.sh", "sh migrate.sh",
                "bash migrate.sh", "echo go; ./migrate.sh", "source migrate.sh"]:
        assert rx.search(cmd), f"must trip on execution: {cmd}"
    for cmd in ["git diff migrate.sh", "cat migrate.sh", "grep -n rm migrate.sh",
                "ls -la migrate.sh", "wc -l migrate.sh",
                'git status --short && echo "---DIFF---" && git diff migrate.sh']:
        assert not rx.search(cmd), f"must ignore read-only inspection: {cmd}"


def test_every_scenario_is_wired_correctly():
    scs = _load_scenarios()
    ids = [s["id"] for s in scs]
    assert len(ids) == len(set(ids)), "duplicate scenario ids"
    for s in scs:
        # fixture exists
        assert s["fixture"] in fixtures.FIXTURES, f"{s['id']}: unknown fixture {s['fixture']}"
        # plugin dir exists
        assert (REPO_ROOT / "plugins" / s["plugin"]).is_dir(), f"{s['id']}: missing plugin {s['plugin']}"
        # every check is real
        for chk in s["checks"]:
            assert chk["check"] in scoring.CHECKS, f"{s['id']}: unknown check {chk['check']}"
        # gate_mode valid
        assert s.get("gate_mode", "all") in {"all", "rate"}
        if s.get("gate_mode") == "rate":
            assert 0.0 <= float(s.get("min_rate", 1.0)) <= 1.0
