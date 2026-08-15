"""Tests for the qa-gatekeeper's coverage-delta check.

The script exists because a passing-count comparison cannot see a suite that shrank.
Two of these tests are regression guards for bugs the script shipped with and that were
caught by running it against a real repo:

- the doubled `-q` trap (repo `addopts = -q` + our `-q` -> `-qq`, which prints per-file
  counts instead of node IDs, parsing to an empty set),
- reporting "OK" from a 0-vs-0 comparison, i.e. a broken check reading as a clean bill.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugins" / "crucible" / "scripts" / "coverage_delta.py"

sys.path.insert(0, str(REPO_ROOT / "evals"))
import fixtures  # noqa: E402


def _load():
    spec = importlib.util.spec_from_file_location("coverage_delta", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cd = _load()


# --------------------------------------------------------------------------- parsing
def test_parse_node_ids_extracts_identities():
    out = "tests/test_a.py::test_one\ntests/test_a.py::test_two\ntests/test_b.py::TestC::test_three\n\n3 tests collected\n"
    assert cd.parse_node_ids(out) == {
        "tests/test_a.py::test_one",
        "tests/test_a.py::test_two",
        "tests/test_b.py::TestC::test_three",
    }


def test_parse_node_ids_ignores_summary_and_noise():
    out = "==== test session starts ====\nwarning: something\nERROR: nope\nno tests ran\n"
    assert cd.parse_node_ids(out) == set()


def test_parse_node_ids_returns_empty_for_double_q_output():
    """`-qq` prints per-file counts with no `::` — the shape that must NOT look like a
    successful collection of zero tests."""
    assert cd.parse_node_ids("tests/test_cms.py: 54\ntests/test_deck_lib.py: 17\n") == set()


# --------------------------------------------------------------------------- reporting
def test_report_flags_removed_tests():
    code, text = cd.report({"t.py::a", "t.py::b"}, {"t.py::a"})
    assert code == 1
    assert "t.py::b" in text and "COVERAGE REGRESSION" in text


def test_report_accepts_pure_additions():
    code, text = cd.report({"t.py::a"}, {"t.py::a", "t.py::b"})
    assert code == 0
    assert "no test present at BASE disappeared" in text


def test_report_flags_a_rename_as_removal():
    """A renamed test is a removal plus an addition; the human must confirm it moved."""
    code, _ = cd.report({"t.py::old_name"}, {"t.py::new_name"})
    assert code == 1


# --------------------------------------------------------------------------- collector choice
def test_detect_collect_cmd_clears_repo_addopts(tmp_path):
    """Regression guard: without `-o addopts=`, a repo configuring `addopts = -q` yields
    `-qq` and the check silently sees no tests at all."""
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = -q\n", encoding="utf-8")
    cmd = cd.detect_collect_cmd(tmp_path)
    assert cmd is not None
    assert "-o" in cmd and "addopts=" in cmd


def test_detect_collect_cmd_returns_none_when_unknown(tmp_path):
    """Better to refuse than to guess: a wrong collector yields an empty set, which would
    look exactly like 'every test was deleted'."""
    assert cd.detect_collect_cmd(tmp_path) is None


# --------------------------------------------------------------------------- end-to-end
def _run_script(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)


def test_end_to_end_detects_the_green_but_shrunken_suite(tmp_path):
    """The case that defeats every count-based gate: HEAD is fully green, coverage halved."""
    repo = fixtures.build("qa_deleted_tests", tmp_path / "r")
    p = _run_script(repo)
    assert p.returncode == 1, p.stdout + p.stderr
    assert "test_perimeter_basic" in p.stdout
    assert "test_perimeter_zero" in p.stdout


def test_end_to_end_no_false_alarm_on_additions(tmp_path):
    repo = fixtures.build("qa_clean", tmp_path / "r")
    p = _run_script(repo)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "test_perimeter" in p.stdout


def test_end_to_end_stays_silent_on_a_failing_test(tmp_path):
    """Separation of concerns: a newly failing test is the test-run gate's job, not this
    script's. Coverage did not shrink, so this must not fire."""
    repo = fixtures.build("qa_regression", tmp_path / "r")
    p = _run_script(repo)
    assert p.returncode == 0, p.stdout + p.stderr


def test_exit_2_when_it_cannot_tell(tmp_path):
    """'I could not determine this' must never share an exit code with 'all clear'."""
    repo = tmp_path / "plain"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=True)
    p = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert p.returncode == 2
    assert "cannot determine" in (p.stdout + p.stderr)


def test_zero_vs_zero_is_not_a_pass(tmp_path, monkeypatch):
    """Regression guard for the bug this script shipped with: on a repo whose collector
    produced no node IDs, BASE=0 and HEAD=0 compared equal and reported OK."""
    repo = fixtures.build("qa_clean", tmp_path / "r")
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--collect-cmd", "echo nothing-here"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
    assert p.returncode == 2, p.stdout + p.stderr
    assert "collected 0 tests at BASE and 0 at HEAD" in (p.stdout + p.stderr)
