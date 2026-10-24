"""Regression tests for bounded runs — the fix for a machine-freezing orphan leak.

What happened: an eval's mutation probe ran a mutant that looped forever appending to a
list, through `uv run ... pytest`. `subprocess.run(timeout=)` killed `uv` (the direct
child); the pytest grandchild, orphaned, kept running — two of them reached ~100 GB and
froze the Mac. Every helper that runs a project's code now goes through `run_bounded`,
which kills the whole tree on timeout and caps the tree's resident memory with a watchdog
(macOS ignores RLIMIT_AS). Both copies are exercised: crucible_common's, and loop-harness's
own (a skill directory cannot import the plugin's scripts/).
"""
from __future__ import annotations

import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import crucible_common
import loop_common

REPO_ROOT = Path(__file__).resolve().parent.parent
POSIX_ONLY = pytest.mark.skipif(sys.platform == "win32", reason="process groups and ps are POSIX")
COPIES = pytest.mark.parametrize("mod", [crucible_common, loop_common], ids=["plugin", "loop-harness"])


@pytest.fixture(autouse=True)
def _reap_markers():
    """Whatever a test started is killed at teardown, pass or fail — so a regression in the
    fix fails the test instead of leaving a runaway on the machine."""
    yield
    if sys.platform == "win32":     # every marker-spawning test is POSIX_ONLY; no pkill there
        return
    subprocess.run(["pkill", "-9", "-f", "bounded-[0-9a-f]{8}|incident-[0-9a-f]{8}|grow-[0-9a-f]{8}"],
                   capture_output=True)


def _alive(marker: str) -> list[str]:
    out = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True).stdout
    return [p for p in out.split() if p]


def _gone(marker: str, within: float = 3.0) -> bool:
    end = time.monotonic() + within
    while time.monotonic() < end:
        if not _alive(marker):
            return True
        time.sleep(0.1)
    return False


def _sleeper(marker: str, setsid: bool = False) -> str:
    """Python source for a grandchild that sleeps under a findable name."""
    head = "import os; os.setsid(); " if setsid else ""
    return f"{head}import time; time.sleep(120)  # {marker}"


@POSIX_ONLY
@COPIES
def test_a_timeout_kills_the_grandchild_not_just_the_child(mod, tmp_path):
    marker = f"bounded-{uuid.uuid4().hex}"
    # the shell is the direct child, as `uv run` and `sh -c` are; python is the grandchild
    cmd = f'"{sys.executable}" -c "{_sleeper(marker)}" & wait'
    b = mod.run_bounded(cmd, tmp_path, 1, shell=True)
    assert b.killed == "timeout" and b.returncode == -1
    assert _gone(marker), f"orphan survived: {_alive(marker)}"


@POSIX_ONLY
@COPIES
def test_a_grandchild_in_its_own_process_group_is_still_killed(mod, tmp_path):
    """Killing the group is not enough when a tool starts its own: the descendant walk is."""
    marker = f"bounded-{uuid.uuid4().hex}"
    cmd = f'"{sys.executable}" -c "{_sleeper(marker, setsid=True)}" & wait'
    mod.run_bounded(cmd, tmp_path, 1, shell=True)
    assert _gone(marker), f"setsid orphan survived: {_alive(marker)}"


@POSIX_ONLY
@COPIES
def test_runaway_memory_is_stopped_by_the_watchdog(mod, tmp_path):
    """The incident's shape: a loop appending without end. The cap trips long before the
    machine does; the timeout here is far longer, so only the watchdog can be what fired."""
    marker = f"grow-{uuid.uuid4().hex}"
    # self-limiting: stops at ~1.5 GB and idles, so if the watchdog regresses this test FAILS
    # (on the timeout) instead of reproducing the incident on the machine running it
    grow = (f"import time\\nchunks = []  # {marker}\\n"
            "while len(chunks) < 75:\\n    chunks.append(bytearray(20_000_000))\\n    time.sleep(0.02)\\n"
            "time.sleep(120)\\n")
    script = tmp_path / f"{marker}.py"
    script.write_text(grow.replace("\\n", "\n"), encoding="utf-8")
    started = time.monotonic()
    b = mod.run_bounded(f'"{sys.executable}" "{script}" & wait', tmp_path, 30, shell=True,
                        mem_limit=300)
    assert b.killed == "memory" and b.peak_mb > 300
    assert time.monotonic() - started < 60
    assert _gone(str(script)), "runaway survived"
    assert "CRUCIBLE_MEM_LIMIT_MB" in b.stderr


@POSIX_ONLY
@COPIES
def test_a_normal_exit_leaves_nothing_running_in_its_group(mod, tmp_path):
    marker = f"bounded-{uuid.uuid4().hex}"
    cmd = f'"{sys.executable}" -c "{_sleeper(marker)}" > /dev/null 2>&1 & echo started'
    b = mod.run_bounded(cmd, tmp_path, 30, shell=True)
    assert b.returncode == 0 and not b.killed and "started" in b.stdout
    assert _gone(marker), f"left behind: {_alive(marker)}"


@COPIES
def test_output_and_exit_code_pass_through(mod, tmp_path):
    b = mod.run_bounded([sys.executable, "-c", "import sys; print('out'); sys.stderr.write('err'); sys.exit(3)"],
                        tmp_path, 30)
    assert (b.returncode, b.stdout.strip(), b.stderr.strip(), b.killed) == (3, "out", "err", "")


def test_cwd_none_means_the_current_directory(tmp_path):
    b = crucible_common.run_bounded([sys.executable, "-c", "import os; print(os.getcwd())"], None, 30)
    assert b.returncode == 0 and Path(b.stdout.strip()).exists()


def test_the_memory_cap_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("CRUCIBLE_MEM_LIMIT_MB", "512")
    assert crucible_common.mem_limit_mb() == 512
    monkeypatch.setenv("CRUCIBLE_MEM_LIMIT_MB", "junk")
    assert crucible_common.mem_limit_mb() == crucible_common.default_mem_limit_mb()


def test_the_default_cap_is_a_quarter_of_ram_at_most(monkeypatch):
    """A runaway on a 16 GB laptop must die at 4 GB, not at a fixed 8 GB."""
    monkeypatch.delenv("CRUCIBLE_MEM_LIMIT_MB", raising=False)
    monkeypatch.setattr(crucible_common, "physical_memory_mb", lambda: 16384)
    assert crucible_common.mem_limit_mb() == 4096
    monkeypatch.setattr(crucible_common, "physical_memory_mb", lambda: 131072)
    assert crucible_common.mem_limit_mb() == 8192


def test_no_call_site_runs_project_code_with_a_bare_timeout():
    """Every place that runs a project's own code must go through run_bounded. A plain
    subprocess.run(timeout=) on those paths is the bug this file exists for."""
    sites = ["plugins/crucible/scripts/mutation_probe.py", "plugins/crucible/scripts/qa_gates.py",
             "plugins/crucible/scripts/invariants_run.py", "plugins/crucible/scripts/integrate.py",
             "evals/harness/runner.py", "plugins/crucible/skills/loop-harness/scripts/loop_sweep.py"]
    for rel in sites:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "run_bounded" in text, f"{rel} does not use run_bounded"


@POSIX_ONLY
def test_the_incident_a_looping_mutant_behind_a_wrapper_leaves_no_orphan(tmp_path):
    """End to end, as it happened: --mutate through a wrapper shell (as `uv run` wraps
    pytest), a mutant that loops appending to a list. Afterwards nothing may be running."""
    import fixtures
    marker = f"incident-{uuid.uuid4().hex}"
    # the loop sleeps per append: a mutant that never ends proves the orphan without
    # allocating its way to the incident if the fix ever regresses
    base = {"scan.py": "import time\n\n\ndef count(n):\n    out = []\n    i = 0\n    while i < n:\n        out.append(i)\n        time.sleep(0.001)\n        i += 1\n    return len(out)\n",
            "tests/test_scan.py": "def test_ok():\n    assert True\n"}
    repo = fixtures.branched_repo(tmp_path / "r", base)
    fixtures._write(repo, "scan.py", base["scan.py"].replace("return len(out)", "return len(out) + 0"))
    fixtures._write(repo, "tests/test_scan.py",
                    "from scan import count\n\n\ndef test_count():\n    assert count(3) == 3\n")
    fixtures._commit_all(repo, "change scan")
    wrapper = tmp_path / "wrap.sh"   # the direct child; pytest is its grandchild
    # no `exec`: like `uv run`, the wrapper stays alive as the parent, so pytest is the
    # GRANDCHILD — the exact shape a direct-child kill orphaned
    wrapper.write_text(f'#!/bin/sh\n"{sys.executable}" -m pytest -q -p no:cacheprovider "$@"\nexit $?\n')
    wrapper.chmod(0o755)
    test_cmd = f"sh {wrapper.as_posix()} --basetemp={(tmp_path / marker).as_posix()}"
    probe = REPO_ROOT / "plugins" / "crucible" / "scripts" / "mutation_probe.py"
    r = subprocess.run([sys.executable, str(probe), "--repo", str(repo), "--mutate",
                        "--test-cmd", test_cmd, "--mutant-timeout", "3"],
                       capture_output=True, text=True, timeout=300,
                       env={**__import__("os").environ, "CRUCIBLE_MEM_LIMIT_MB": "400"})
    assert r.returncode in (0, 1), r.stdout + r.stderr
    assert _gone(marker, within=5), f"orphaned test runner after --mutate: {_alive(marker)}"
