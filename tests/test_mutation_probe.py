"""Tests for mutation_probe.py — "delete the fix" and planted defects, in a throwaway copy.

Each repo here is built so the right answer is known: a fix whose test depends on it, a
test that asserts nothing the fix changed, an additive change, a test that runs against
some other copy of the code. The safety property — the user's tree is never written — is
checked by hashing it before and after.
"""
from __future__ import annotations

import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugins" / "crucible" / "scripts" / "mutation_probe.py"

sys.path.insert(0, str(REPO_ROOT / "evals"))
import fixtures  # noqa: E402


def _load():
    spec = importlib.util.spec_from_file_location("mutation_probe", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mp = _load()

_BUGGY = "def clamp(x, lo, hi):\n    return max(lo, x)\n"
_FIXED = "def clamp(x, lo, hi):\n    return min(hi, max(lo, x))\n"
_REAL_TEST = ("from calc import clamp\n\n\n"
              "def test_clamp_caps_at_hi():\n    assert clamp(9, 0, 5) == 5\n\n\n"
              "def test_clamp_floors_at_lo():\n    assert clamp(-1, 0, 5) == 0\n")
_VACUOUS_TEST = ("from calc import clamp\n\n\n"
                 "def test_clamp_returns_something():\n    assert clamp(9, 0, 5) is not None\n")


def _run(repo, *args):
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600)
    return r.returncode, r.stdout + r.stderr


def _repo(tmp_path, base: dict[str, str], change: dict[str, str]) -> Path:
    repo = fixtures.branched_repo(tmp_path / "r", base)
    for rel, text in change.items():
        fixtures._write(repo, rel, text)
    fixtures._commit_all(repo, "change")
    return repo


def _tree_hash(repo: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts):
        h.update(f.relative_to(repo).as_posix().encode())
        h.update(f.read_bytes())
    return h.hexdigest()


_BASE = {"calc.py": _BUGGY, "tests/test_smoke.py": "def test_ok():\n    assert True\n"}


# --------------------------------------------------------------------------- --revert
def test_a_test_that_depends_on_the_fix_fails_without_it(tmp_path):
    repo = _repo(tmp_path, _BASE, {"calc.py": _FIXED, "tests/test_calc.py": _REAL_TEST})
    code, out = _run(repo, "--revert")
    assert code == 0, out


def test_a_test_that_passes_without_the_fix_is_reported(tmp_path):
    """The delete-the-fix rule: this test would have passed before the change, too."""
    repo = _repo(tmp_path, _BASE, {"calc.py": _FIXED, "tests/test_calc.py": _VACUOUS_TEST})
    code, out = _run(repo, "--revert")
    assert code == 1 and "tests/test_calc.py" in out, out


def test_an_additive_change_is_a_skip_not_a_verdict(tmp_path):
    repo = _repo(tmp_path, _BASE, {"extra.py": "def f():\n    return 2\n",
                                   "tests/test_extra.py": "from extra import f\n\n\ndef test_f():\n    assert f() == 2\n"})
    code, out = _run(repo, "--revert")
    assert code == 3 and "additive" in out


def test_no_changed_test_is_a_skip(tmp_path):
    repo = _repo(tmp_path, _BASE, {"calc.py": _FIXED})
    code, out = _run(repo, "--revert")
    assert code == 3 and "SKIP" in out


def test_uncommitted_work_is_probed_and_left_untouched(tmp_path):
    repo = _repo(tmp_path, _BASE, {"tests/test_calc.py": _REAL_TEST.replace("caps_at_hi", "x")})
    fixtures._write(repo, "calc.py", _FIXED)                  # uncommitted fix
    before = _tree_hash(repo)
    code, out = _run(repo, "--revert")
    assert code == 0, out
    assert _tree_hash(repo) == before
    assert subprocess.run(["git", "-C", str(repo), "stash", "list"], capture_output=True,
                          text=True).stdout == ""


# --------------------------------------------------------------------------- canaries
def test_exit_2_when_the_tests_are_red_in_the_copy(tmp_path):
    repo = _repo(tmp_path, _BASE, {"calc.py": _BUGGY.replace("max", "min"),
                                   "tests/test_calc.py": _REAL_TEST})
    code, out = _run(repo, "--revert")
    assert code == 2 and "unmodified copy" in out


def test_exit_2_when_the_tests_run_some_other_copy_of_the_code(tmp_path):
    """Tests that import the module from outside the repo pass whatever the copy holds —
    without the sentinel canary every probe would report a confident wrong answer."""
    outside = tmp_path / "installed"
    fixtures._write(outside, "calc.py", _FIXED)
    redirect = (f"import sys\nsys.path.insert(0, {outside.as_posix()!r})\n"
                "sys.modules.pop('calc', None)\n")
    repo = _repo(tmp_path, _BASE, {"calc.py": _FIXED,
                                   "tests/test_calc.py": redirect + _REAL_TEST})
    code, out = _run(repo, "--revert")
    assert code == 2 and "some other copy" in out, out


# --------------------------------------------------------------------------- --mutate
def test_strong_tests_kill_every_mutant(tmp_path):
    repo = _repo(tmp_path, _BASE, {"calc.py": _FIXED, "tests/test_calc.py": _REAL_TEST
                                   + "\n\ndef test_inside():\n    assert clamp(3, 0, 5) == 3\n"})
    code, out = _run(repo, "--mutate")
    assert code == 0, out


def test_weak_tests_let_mutants_survive(tmp_path):
    repo = _repo(tmp_path, _BASE, {"calc.py": _FIXED, "tests/test_calc.py": _VACUOUS_TEST})
    code, out = _run(repo, "--mutate")
    assert code == 1 and "SURVIVED" in out and "calc.py:2" in out, out


def test_mutate_leaves_the_tree_untouched(tmp_path):
    repo = _repo(tmp_path, _BASE, {"calc.py": _FIXED, "tests/test_calc.py": _VACUOUS_TEST})
    before = _tree_hash(repo)
    _run(repo, "--mutate")
    assert _tree_hash(repo) == before


def test_no_changed_function_is_a_skip(tmp_path):
    repo = _repo(tmp_path, _BASE, {"README.md": "# hi\n"})
    code, out = _run(repo, "--mutate")
    assert code == 3


def test_the_budget_is_spread_across_operators():
    sites = [("a.py", "constant", n, n) for n in range(10)] + [("a.py", "compare", 1, 99)]
    chosen = mp.pick(sites, 3)
    assert {c[1] for c in chosen} == {"constant", "compare"} and len(chosen) == 3


def test_every_operator_produces_parseable_source():
    src = ("def f(a, b):\n    if a < b and b:\n        return a + 1\n    return a == b\n")
    tree = __import__("ast").parse(src)
    for op, _line, ordinal in mp._sites(tree, {1, 2, 3, 4}):
        mutated = mp._apply(src, op, ordinal)
        assert mutated != src and __import__("ast").parse(mutated)


# --------------------------------------------------------------------------- could not determine
def test_exit_2_without_a_mode(tmp_path):
    repo = _repo(tmp_path, _BASE, {"calc.py": _FIXED})
    assert _run(repo)[0] == 2


def test_exit_2_outside_a_git_repository(tmp_path):
    code, out = _run(tmp_path, "--revert")
    assert code == 2 and "not a git repository" in out


def test_augmented_assignment_is_mutated():
    """`i += 1` is as common as `a + b`; a probe that skipped it missed a whole class of
    off-by-sign defects — and the mutant that loops forever."""
    src = "def f(n):\n    i = 0\n    while i < n:\n        i += 1\n    return i\n"
    tree = __import__("ast").parse(src)
    mutated = [mp._apply(src, op, o) for op, _l, o in mp._sites(tree, {1, 2, 3, 4, 5}) if op == "arith"]
    assert any("i -= 1" in m for m in mutated)


def test_bytecode_left_by_an_earlier_run_is_not_a_changed_source(tmp_path):
    """An earlier gate's test run writes __pycache__; in a repo with no .gitignore that is
    untracked, and the probe once treated it as a source change to revert."""
    repo = _repo(tmp_path, _BASE, {"tests/test_more.py": "def test_more():\n    assert True\n"})
    subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=repo,
                   capture_output=True)
    assert any(repo.rglob("*.pyc"))
    code, out = _run(repo, "--revert")
    assert code == 3 and "only tests" in out, out


# --------------------------------------------------------------------------- fail fast
def test_mutate_fails_fast_when_the_changed_tests_need_data_the_copy_lacks(tmp_path):
    """The copy holds only git's files. A suite needing ignored data must be caught by the
    changed tests alone, before the (here: marker-writing) full suite is run in the copy."""
    marker = tmp_path / "full-suite-ran"
    slow = (f"def test_full_suite():\n    open({marker.as_posix()!r}, 'w').close()\n")
    needs_data = ("from calc import clamp\n\n\n"
                  "def test_reads_ignored_data():\n    assert open('store.txt').read() == 'x'\n")
    repo = fixtures.branched_repo(tmp_path / "r", {**_BASE, ".gitignore": "store.txt\n",
                                                   "tests/test_full.py": slow})
    fixtures._write(repo, "store.txt", "x")
    fixtures._write(repo, "calc.py", _FIXED)
    fixtures._write(repo, "tests/test_calc.py", needs_data)
    fixtures._commit_all(repo, "change")
    code, out = _run(repo, "--mutate")
    assert code == 2 and "changed tests do not pass in an unmodified copy" in out, out
    assert not marker.exists(), "the full suite ran in the copy before the quick check failed"


def test_canary_timeout_bounds_the_clean_full_suite_run(tmp_path):
    base = {**_BASE, "tests/test_smoke.py": "import time\n\n\ndef test_ok():\n    time.sleep(8)\n"}
    repo = _repo(tmp_path, base, {"calc.py": _FIXED, "tests/test_calc.py": _REAL_TEST})
    code, out = _run(repo, "--mutate", "--canary-timeout", "2")
    assert code == 2 and "timed out after 2s" in out, out
