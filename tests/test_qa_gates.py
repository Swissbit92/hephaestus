"""Tests for qa_gates.py — Phase 4.0 in one call, each gate once, one verdict.

What it must never do is change a gate's answer: aggregation keeps could-not-determine
apart from pass, the test lane stays serial unless the repo declares otherwise (a suite
that binds a fixed port goes flaky when two copies run at once), and a verdict is only
"current" for the exact tree it was computed on. The cost claim — one full suite, one
branch-point collection, zero once cached — is pinned with a conftest that logs every
pytest session.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugins" / "crucible" / "scripts" / "qa_gates.py"

sys.path.insert(0, str(REPO_ROOT / "evals"))
import fixtures  # noqa: E402


def _load():
    spec = importlib.util.spec_from_file_location("qa_gates", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


qg = _load()

_COUNTING_CONFTEST = (
    "import os, time\n\n"
    "def pytest_sessionstart(session):\n"
    "    log = os.environ.get('PYTEST_COUNT_LOG')\n"
    "    if log:\n"
    "        kind = 'collect' if session.config.option.collectonly else 'run'\n"
    "        with open(log, 'a') as fh:\n"
    "            fh.write(f'{kind} start {time.monotonic()} {os.getpid()}\\n')\n"
    "    time.sleep(float(os.environ.get('PYTEST_COUNT_HOLD', '0')))\n\n"
    "def pytest_sessionfinish(session):\n"
    "    log = os.environ.get('PYTEST_COUNT_LOG')\n"
    "    if log:\n"
    "        with open(log, 'a') as fh:\n"
    "            fh.write(f'x end {time.monotonic()} {os.getpid()}\\n')\n"
)


def _repo(tmp_path: Path) -> Path:
    repo = fixtures.branched_repo(tmp_path / "r", {
        "pyproject.toml": "[project]\nname='c'\nversion='0'\n[tool.pytest.ini_options]\ntestpaths=['tests']\n",
        "calc.py": "def clamp(x, lo, hi):\n    return max(lo, x)\n",
        "tests/test_smoke.py": "def test_ok():\n    assert True\n",
        "conftest.py": _COUNTING_CONFTEST,
    })
    fixtures._write(repo, "calc.py", "def clamp(x, lo, hi):\n    return min(hi, max(lo, x))\n")
    fixtures._write(repo, "tests/test_calc.py",
                    "from calc import clamp\n\n\ndef test_hi():\n    assert clamp(9, 0, 5) == 5\n")
    fixtures._commit_all(repo, "fix clamp")
    return repo


def _run(repo: Path, *args: str, log: Path | None = None, hold: float = 0.0):
    import os
    env = {**os.environ, "PYTEST_COUNT_HOLD": str(hold)}
    if log is not None:
        env["PYTEST_COUNT_LOG"] = str(log)
    # emitted gate lines spell the interpreter `python3` on POSIX; make that the one
    # running these tests, so pytest is importable in every gate
    bindir = log.parent / "bin" if log is not None else None
    if bindir is not None:
        bindir.mkdir(exist_ok=True)
        shim = bindir / "python3"
        if not shim.exists():
            # a wrapper, not a symlink: a symlinked venv interpreter loses its venv
            shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
            shim.chmod(0o755)
        env["PATH"] = f"{bindir}{os.pathsep}{env.get('PATH', '')}"
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600, env=env)
    return r.returncode, r.stdout + r.stderr


def _sessions(log: Path) -> list[str]:
    return [ln.split()[0] for ln in log.read_text().splitlines() if "start" in ln]


# --------------------------------------------------------------------------- aggregation
@pytest.mark.parametrize("codes,expected", [
    ([0, 0], 0), ([0, 1, 2], 1), ([0, 2], 2), ([3, 3], 3), ([0, 3], 0), ([], 3)])
def test_aggregate_never_folds_could_not_determine_into_a_pass(codes, expected):
    assert qg.aggregate([{"exit": c} for c in codes]) == expected


def test_unknown_gates_default_to_the_serial_lane():
    assert qg.STATIC.search('python3 "/x/metric_delta.py" --metric clones --repo .')
    assert not qg.STATIC.search("python3 -m pytest")
    assert not qg.STATIC.search("make check")


# --------------------------------------------------------------------------- the cost claim
@pytest.mark.skipif(sys.platform == "win32", reason="the python3 shim is a POSIX sh script")
def test_one_round_runs_the_suite_once_and_caches_the_base(tmp_path):
    repo = _repo(tmp_path)
    log = tmp_path / "count.log"
    code, out = _run(repo, log=log)
    assert code == 0, out
    first = _sessions(log)
    assert first.count("collect") == 2          # head + base, once each
    log.unlink()
    code, out = _run(repo, log=log)
    assert code == 0 and "(cached)" not in out  # the summary stays compact
    second = _sessions(log)
    assert second.count("collect") == 1         # the base came from the cache
    # exactly one FULL suite run per round; the rest are the revert probe's changed tests
    assert first.count("run") == second.count("run")


@pytest.mark.skipif(sys.platform == "win32", reason="the python3 shim is a POSIX sh script")
def test_the_test_lane_never_overlaps_by_default(tmp_path):
    repo = _repo(tmp_path)
    log = tmp_path / "count.log"
    # every session is held open 0.3 s, so two concurrent ones must overlap — fast fixture
    # tests otherwise finish too quickly for an overlap to be anything but luck
    _run(repo, log=log, hold=0.3)
    # pair each session's start and end by pid — file order interleaves under concurrency
    starts, spans = {}, []
    for ln in log.read_text().splitlines():
        _kind, what, t, pid = ln.split()
        if what == "start":
            starts[pid] = float(t)
        else:
            spans.append((starts.pop(pid), float(t)))
    spans.sort()
    assert len(spans) >= 3
    assert all(a_end <= b_start for (_, a_end), (b_start, _) in zip(spans, spans[1:]))


# --------------------------------------------------------------------------- the verdict file
@pytest.mark.skipif(sys.platform == "win32", reason="the python3 shim is a POSIX sh script")
def test_show_returns_the_verdict_only_for_the_tree_it_was_computed_on(tmp_path):
    repo = _repo(tmp_path)
    log = tmp_path / "count.log"
    assert _run(repo, log=log)[0] == 0
    code, out = _run(repo, "--show", log=log)
    assert code == 0 and "QA-GATES: PASS" in out
    fixtures._write(repo, "calc.py", "def clamp(x, lo, hi):\n    return lo\n")   # any edit
    code, out = _run(repo, "--show", log=log)
    assert code == 2 and "no QA verdict for the current tree" in out


def test_a_malformed_parallel_declaration_is_undetermined(tmp_path):
    repo = _repo(tmp_path)
    fixtures._write(repo, ".crucible/qa.json", '{"parallel_tests": "yes"}')
    code, out = _run(repo)
    assert code == 2 and "parallel_tests" in out


def test_no_gates_is_a_skip(tmp_path):
    repo = fixtures.branched_repo(tmp_path / "r", {"README.md": "# hi\n"})
    code, out = _run(repo)
    assert code == 3 and "SKIP" in out


def test_a_failing_gate_shows_its_tail_and_fails_the_round(tmp_path):
    repo = _repo(tmp_path)
    fixtures._write(repo, "tests/test_calc.py",
                    "from calc import clamp\n\n\ndef test_hi():\n    assert clamp(9, 0, 5) == 9\n")
    log = tmp_path / "count.log"
    code, out = _run(repo, log=log) if sys.platform != "win32" else _run(repo)
    assert code in (1, 2)
    assert "QA-GATES:" in out and "--- tests" in out


# --------------------------------------------------------------------------- the base cache
def test_the_cache_key_changes_with_the_command_and_the_base():
    import crucible_common as cc
    a = cc.cache_key("coverage_delta.base", "abc", ["pytest"], "s1")
    assert a != cc.cache_key("coverage_delta.base", "abd", ["pytest"], "s1")
    assert a != cc.cache_key("coverage_delta.base", "abc", ["pytest", "-x"], "s1")
    assert a != cc.cache_key("coverage_delta.base", "abc", ["pytest"], "s2")


def test_no_cache_env_disables_the_cache(monkeypatch):
    import crucible_common as cc
    monkeypatch.setenv("CRUCIBLE_NO_CACHE", "1")
    assert cc.cache_disabled() is True
    monkeypatch.setenv("CRUCIBLE_NO_CACHE", "0")
    assert cc.cache_disabled() is False
