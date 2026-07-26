"""Headless tests for the live-side eval pieces that DON'T need claude: the git/file
snapshot (world.py), the fixture builders, and scenarios.json integrity. These use the real
git CLI (always present in this repo's environment)."""
from __future__ import annotations

import json
import sqlite3
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


# --------------------------------------------------------------------------- scenarios.json integrity
def _load_scenarios():
    return json.loads(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]


def test_scenarios_file_loads_and_has_entries():
    scs = _load_scenarios()
    assert len(scs) >= 8


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
