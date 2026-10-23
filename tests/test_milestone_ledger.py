"""Tests for develop's per-milestone fix budget (milestone_ledger.py).

The budget replaces an unbounded "fix, re-run QA, repeat until PASS". The case it exists
for is the one a same-class rule misses: rounds that each fail for a different reason, so
every round looks like progress. Most tests here drive the CLI against a real git repo,
because the ledger's location (the git dir, keyed by branch) is part of the contract.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugins" / "crucible" / "scripts" / "milestone_ledger.py"

sys.path.insert(0, str(REPO_ROOT / "evals"))
import fixtures  # noqa: E402


def _load():
    spec = importlib.util.spec_from_file_location("milestone_ledger", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ml = _load()

T0 = "2026-10-23T09:00:00Z"


def _run(repo, *args, now=T0):
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--now", now, *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=60)
    first = r.stdout.splitlines()[0] if r.stdout.strip() else ""
    return r.returncode, first, r.stdout + r.stderr


@pytest.fixture
def repo(tmp_path):
    """A clean feature branch with an initialised FULL ledger and M1 started."""
    fixtures._ledger_repo(tmp_path / "r")
    r = tmp_path / "r"
    fixtures._commit_all(r, "plan")
    assert _run(r, "init", "--tier", "FULL", "--estimate", "M1=45", "--estimate", "M2=30",
                "--user-said", "plan approved")[0] == 0
    assert _run(r, "start", "M1")[0] == 0
    return r


def _reject(repo, kind, m="M1", now=T0):
    return _run(repo, "record", m, "--verdict", "REJECT", "--kind", kind, now=now)


# --------------------------------------------------------------------------- the fixture contract
def test_the_fix_cap_fixture_reads_as_a_rounds_checkpoint(tmp_path):
    """The eval fixture and this script must agree on the ledger format, or the scenario
    built on it measures a parse error rather than develop's behaviour."""
    repo = fixtures.build("develop_at_fix_cap", tmp_path / "r")
    code, first, out = _run(repo, "status", "M1", now=ml.fmt_at(ml._dt.datetime.now(ml._dt.timezone.utc)))
    assert (code, first) == (1, "STOP CHECKPOINT-ROUNDS"), out
    assert "ship" in out and "restart" in out


def test_the_next_milestone_fixture_has_m1_done(tmp_path):
    repo = fixtures.build("develop_next_milestone", tmp_path / "r")
    code, first, out = _run(repo, "status", "M1")
    assert (code, first) == (0, "DONE"), out


def test_the_ledger_never_touches_the_work_tree(repo):
    _reject(repo, "tests")
    r = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True,
                       text=True, encoding="utf-8")
    assert r.stdout.strip() == ""


# --------------------------------------------------------------------------- fix rounds
def test_every_failure_counts_whatever_its_kind(repo):
    """Three different kinds: no repeat, still a spent budget. This is the 7-round case."""
    assert _reject(repo, "tests")[:2] == (0, "PROCEED")
    assert _reject(repo, "lint")[:2] == (0, "PROCEED")
    code, first, out = _reject(repo, "review")
    assert (code, first) == (1, "STOP CHECKPOINT-ROUNDS"), out


def test_the_same_kind_twice_demands_a_diagnosis(repo):
    _reject(repo, "tests")
    assert _reject(repo, "tests")[:2] == (1, "STOP DIAGNOSE")
    assert _run(repo, "diagnose", "M1", "--note", "split keeps the trailing empty field")[:2] \
        == (0, "PROCEED")


def test_the_checkpoint_outranks_diagnose(repo):
    """Once the budget is spent the question is whether to go on at all."""
    _reject(repo, "lint")
    _reject(repo, "tests")
    assert _reject(repo, "tests")[:2] == (1, "STOP CHECKPOINT-ROUNDS")


def test_an_empty_diagnosis_is_refused(repo):
    _reject(repo, "tests")
    _reject(repo, "tests")
    code, _, out = _run(repo, "diagnose", "M1", "--note", "  ")
    assert code == 2 and "refused" in out


def test_setup_failures_have_their_own_budget(repo):
    """A broken toolchain must not spend the fix budget before any fixing happens."""
    _reject(repo, "setup")
    _reject(repo, "setup")
    assert _reject(repo, "tests")[:2] == (0, "PROCEED")
    assert _reject(repo, "setup")[:2] == (1, "STOP CHECKPOINT-SETUP")


def test_time_over_twice_the_estimate_is_a_checkpoint(repo):
    assert _run(repo, "status", "M1", now="2026-10-23T10:29:00Z")[:2] == (0, "PROCEED")
    assert _run(repo, "status", "M1", now="2026-10-23T10:31:00Z")[:2] == (1, "STOP CHECKPOINT-TIME")


# --------------------------------------------------------------------------- the user's choices
@pytest.mark.parametrize("cmd", ["extend", "restart", "ship"])
def test_changing_the_budget_needs_the_users_words(repo, cmd):
    code, _, out = _run(repo, cmd, "M1")
    assert code == 2 and "--user-said" in out


def test_extend_grants_another_budget_and_report_shows_who_said_so(repo):
    for kind in ("tests", "lint", "review"):
        _reject(repo, kind)
    assert _run(repo, "extend", "M1", "--user-said", "continue, one more go")[:2] == (0, "PROCEED")
    _, _, out = _run(repo, "report")
    assert "fix round 3/6" in out and "continue, one more go" in out


def test_restart_resets_the_rounds(repo):
    for kind in ("tests", "lint", "review"):
        _reject(repo, kind)
    assert _run(repo, "restart", "M1", "--user-said", "restart from the plan")[:2] == (0, "PROCEED")
    assert "fix round 0/3" in _run(repo, "status", "M1")[2]


def test_ship_closes_the_milestone(repo):
    for kind in ("tests", "lint", "review"):
        _reject(repo, kind)
    assert _run(repo, "ship", "M1", "--user-said", "ship it")[:2] == (0, "DONE")


def test_init_refuses_to_overwrite_an_existing_ledger(repo):
    code, _, out = _run(repo, "init", "--user-said", "again")
    assert code == 2 and "already exists" in out


# --------------------------------------------------------------------------- research
def test_a_full_pass_without_research_is_not_done(repo):
    code, first, out = _run(repo, "record", "M1", "--verdict", "PASS", "--kind", "tests")
    assert (code, first) == (1, "STOP RESEARCH-MISSING"), out
    assert _run(repo, "research", "M1", "--note", "str.split docs")[:2] == (0, "DONE")


def test_light_work_does_not_need_milestone_research(tmp_path):
    fixtures._ledger_repo(tmp_path / "r")
    r = tmp_path / "r"
    _run(r, "init", "--tier", "LIGHT", "--user-said", "go")
    _run(r, "start", "M1")
    assert _run(r, "record", "M1", "--verdict", "PASS")[:2] == (0, "DONE")


# --------------------------------------------------------------------------- could not determine
def test_exit_2_when_there_is_no_ledger(tmp_path):
    fixtures._ledger_repo(tmp_path / "r")
    code, _, out = _run(tmp_path / "r", "status", "M1")
    assert code == 2 and "cannot determine" in out


def test_exit_2_on_detached_head(repo):
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "--detach"], check=True)
    code, _, out = _run(repo, "status", "M1")
    assert code == 2 and "detached" in out


def test_exit_2_for_a_milestone_that_never_started(repo):
    code, _, out = _run(repo, "record", "M2", "--verdict", "REJECT")
    assert code == 2 and "never started" in out


def test_exit_2_for_an_unreadable_ledger(repo):
    path = ml.ledger_path(repo)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    code, _, out = _run(repo, "status", "M1")
    assert code == 2 and "not JSON" in out


def test_each_branch_has_its_own_ledger(repo):
    subprocess.run(["git", "-C", str(repo), "switch", "-q", "-c", "feature/other"], check=True)
    assert _run(repo, "status", "M1")[0] == 2   # no ledger on the new branch


# --------------------------------------------------------------------------- the pure fold
def test_milestone_state_counts_only_its_own_milestone():
    events = [{"event": "init", "fix_cap": 3, "setup_cap": 3, "estimates": {}},
              {"event": "start", "milestone": "M1", "at": T0},
              {"event": "verdict", "milestone": "M2", "verdict": "REJECT", "kind": "tests"},
              {"event": "verdict", "milestone": "M1", "verdict": "REJECT", "kind": "tests"}]
    assert ml.milestone_state(events, "M1")["rounds"] == 1


def test_the_eval_harness_reads_the_cap_this_script_enforces():
    """run_evals records develop_fix_cap by reading DEFAULT_FIX_CAP from this file."""
    assert ml.DEFAULT_FIX_CAP == 3
    assert "\nDEFAULT_FIX_CAP = 3\n" in SCRIPT.read_text(encoding="utf-8")
