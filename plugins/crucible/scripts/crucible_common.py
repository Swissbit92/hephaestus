#!/usr/bin/env python3
"""Helpers the crucible gate scripts share — imported, not copied.

Every script here used to carry its own copy of the UTF-8 stdio fix, the subprocess
wrapper and the branch-point lookup. Copies drift: the one that learns a lesson (pin the
encoding, never spell the interpreter `python3`, read the integration target start-branch
recorded) teaches it to nobody else. A duplicate-code gate also has to be able to pass on
the code that ships it.

Not a CLI. Importing it has no side effects.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_TARGETS = ("dev", "main", "master", "trunk")


def utf8_stdio() -> None:
    """Force UTF-8 on the streams a script writes to.

    Windows consoles default to a legacy codepage (commonly cp1252), so a single em-dash
    or check-mark in otherwise successful output raises UnicodeEncodeError *after* the
    work is done — turning a passing gate into exit 1, which reads as a real failure.
    Reconfiguring is a no-op on platforms that are already UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # a detached or captured stream (pytest); nothing to reconfigure


def python_exe() -> str:
    """The interpreter to re-invoke. Never the literal "python3": on Windows that name is
    usually the Microsoft Store stub, which prints an ad, runs nothing and exits 49. It
    also pins child runs to the interpreter running this script, so a venv's pytest is not
    silently swapped for the system one."""
    return sys.executable or shutil.which("python3") or shutil.which("python") or "python3"


def run(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str]:
    """(returncode, stdout+stderr). 127 when the command could not be started or timed out.

    The encoding is pinned rather than left to the locale: with text=True alone, Windows
    decodes via the locale (commonly cp1252), and one non-ASCII byte in a test id or a
    traceback then raises or mojibakes mid-parse."""
    try:
        b = run_bounded(cmd, cwd, timeout)
    except OSError as e:
        return 127, f"{type(e).__name__}: {e}"
    if b.killed:
        return 127, b.stdout + b.stderr
    return b.returncode, b.stdout + b.stderr


def git_out(repo: Path, *args: str) -> str | None:
    """Stripped stdout of a git command, or None when it failed."""
    rc, out = run(["git", *args], repo, timeout=60)
    return out.strip() if rc == 0 else None


def current_branch(repo: Path) -> str | None:
    """The checked-out branch, or None on a detached HEAD (where there is no branch to key
    anything to)."""
    name = git_out(repo, "rev-parse", "--abbrev-ref", "HEAD")
    return name if name and name != "HEAD" else None


def git_branches(repo: Path) -> list[str]:
    rc, out = run(["git", "branch", "--format=%(refname:short)"], repo)
    return [b.strip() for b in out.splitlines() if b.strip()] if rc == 0 else []


def recorded_target(repo: Path) -> str | None:
    """The integration target start-branch wrote into git config for this branch.

    It is the only authoritative answer — detection is a heuristic, and in an ambiguous
    repo it can pick a different branch than the one the work actually forked from."""
    branch = current_branch(repo)
    if not branch:
        return None
    return git_out(repo, "config", "--get", f"branch.{branch}.integrationTarget") or None


def detect_target(repo: Path, preferred: str | None = None) -> str | None:
    """The long-lived branch this work integrates into: an explicit choice, else the target
    recorded at branch creation, else the first conventional name that exists."""
    branches = set(git_branches(repo))
    if preferred:
        return preferred if preferred in branches else None
    recorded = recorded_target(repo)
    if recorded and recorded in branches:
        return recorded
    for name in DEFAULT_TARGETS:
        if name in branches:
            return name
    return None


def merge_base(repo: Path, target: str) -> str | None:
    rc, out = run(["git", "merge-base", "HEAD", target], repo)
    return out.strip() if rc == 0 and out.strip() else None


# --------------------------------------------------------------------------- base-side cache
# What a gate computes at the BRANCH POINT depends only on that commit and on how it was
# computed, so it can be reused across QA rounds — that side costs a worktree and a full
# collection or lint run every time, and it is the same answer every time. Only the base
# side is cached: the working tree changes between rounds, and a stale head-side result
# would be exactly the wrong-but-green answer these gates exist to prevent.
#
# The key covers the base sha, the command, the interpreter (path and version) and the
# calling script's own bytes, so upgrading a gate script or switching venvs misses the
# cache. Known gap: upgrading packages inside the same venv, at the same interpreter path,
# does not change the key — pass --no-cache (or CRUCIBLE_NO_CACHE=1) after doing that.
# Only successful results are stored; a could-not-determine is never cached.

def git_common_dir(repo: Path) -> Path | None:
    """Shared by every worktree of the repo, so worktrees share one cache."""
    out = git_out(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if out and Path(out).is_absolute():
        return Path(out)
    out = git_out(repo, "rev-parse", "--git-common-dir")   # git < 2.31: may be relative
    return (Path(repo) / out).resolve() if out else None


def cache_key(*parts: object) -> str:
    import hashlib
    h = hashlib.sha256()
    for part in (*parts, sys.executable, sys.version):
        h.update(repr(part).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()[:32]


def script_digest(path: str | Path) -> str:
    import hashlib
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    except OSError:
        return "unreadable"


def cache_disabled(flag: bool = False) -> bool:
    import os
    return flag or os.environ.get("CRUCIBLE_NO_CACHE", "") not in ("", "0")


def cache_get(repo: Path, key: str):
    import json
    root = git_common_dir(repo)
    if root is None:
        return None
    try:
        return json.loads((root / "crucible" / "cache" / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_put(repo: Path, key: str, value) -> None:
    """Atomic: write a temp file, then rename over the target, so a concurrent reader sees
    the old entry or the new one, never half of one."""
    import json
    import os
    import tempfile
    root = git_common_dir(repo)
    if root is None:
        return
    d = root / "crucible" / "cache"
    try:
        d.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(d), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(value, fh)
        os.replace(tmp, d / f"{key}.json")
    except OSError:
        pass   # a cache that cannot be written is a cache miss next time, nothing worse


# --------------------------------------------------------------------------- CI and remotes
# Read from the TARGET's tree, never the working tree: a branch that adds a workflow says
# nothing about whether the branch it merges into checks pull requests.
CI_MARKERS = (
    (r"^\.github/workflows/[^/]+\.ya?ml$", "github-actions"),
    (r"^\.gitlab-ci\.ya?ml$", "gitlab-ci"),
    (r"^\.circleci/config\.ya?ml$", "circleci"),
    (r"^azure-pipelines\.ya?ml$", "azure-pipelines"),
    (r"^bitbucket-pipelines\.ya?ml$", "bitbucket-pipelines"),
    (r"^Jenkinsfile$", "jenkins"),
    (r"^\.buildkite/", "buildkite"),
    (r"^\.travis\.ya?ml$", "travis"),
    (r"^\.drone\.ya?ml$", "drone"),
    (r"^\.woodpecker(\.ya?ml|/)", "woodpecker"),
)


def remote_ref(repo: Path, branch: str) -> str | None:
    """`origin/<branch>` (or the first remote that has it) — what a PR would target."""
    remotes = (git_out(repo, "remote") or "").split()
    for remote in (["origin"] if "origin" in remotes else []) + [r for r in remotes if r != "origin"]:
        ref = f"{remote}/{branch}"
        if git_out(repo, "rev-parse", "--verify", "--quiet", ref):
            return ref
    return None


def detect_ci(repo: Path, ref: str) -> list[str] | None:
    """CI systems configured in `ref`'s tree, sorted; None when the tree cannot be read."""
    import re
    rc, out = run(["git", "ls-tree", "-r", "--name-only", ref], repo, timeout=60)
    if rc != 0:
        return None
    found = set()
    for path in out.splitlines():
        for pattern, name in CI_MARKERS:
            if re.search(pattern, path):
                found.add(name)
    return sorted(found)


# --------------------------------------------------------------------------- bounded runs
# Running the PROJECT's code (tests, gate commands, checks, a dry run) can hang or run away:
# a planted mutant loops forever appending to a list. subprocess.run(timeout=) then kills
# only the direct child — `uv`, `sh`, `claude` — and the real worker, a grandchild, keeps
# running, orphaned. Two such orphans once grew to ~100 GB each and froze the machine. So:
#   - every child gets its own session (POSIX) / process group (Windows);
#   - on timeout, or when the tree's resident memory passes a cap, the whole tree is killed:
#     the group, plus every descendant found while the parent was still alive (a tool may
#     start its own group), and then reaped;
#   - after a normal exit, anything the command left running in its group is killed too.
# The memory cap is a watchdog, not an rlimit: macOS does not enforce RLIMIT_AS. It is a
# ceiling for a RUNAWAY — normal test runs use megabytes — and it is relative to the machine:
# min(8 GB, a quarter of physical RAM), so a 16 GB laptop stops a runaway at 4 GB, long
# before it can take the machine. CRUCIBLE_MEM_LIMIT_MB overrides it (0 disables).

DEFAULT_MEM_LIMIT_MB = 8192
RAM_FRACTION = 4          # the cap is at most 1/RAM_FRACTION of physical memory


def physical_memory_mb() -> int | None:
    import os
    try:
        return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        return None


def default_mem_limit_mb() -> int:
    phys = physical_memory_mb()
    return min(DEFAULT_MEM_LIMIT_MB, phys // RAM_FRACTION) if phys else DEFAULT_MEM_LIMIT_MB


class Bounded:
    """The outcome of a bounded run. `killed` is "", "timeout" or "memory"."""

    def __init__(self, returncode: int, stdout: str, stderr: str, killed: str = "",
                 peak_mb: int = 0) -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr
        self.killed, self.peak_mb = killed, peak_mb


def mem_limit_mb() -> int:
    import os
    raw = os.environ.get("CRUCIBLE_MEM_LIMIT_MB")
    if raw is None:
        return default_mem_limit_mb()
    try:
        return max(0, int(raw))
    except ValueError:
        return default_mem_limit_mb()


def _ps_table() -> list[tuple[int, int, int, int]]:
    """(pid, ppid, pgid, rss_kb) for every process — POSIX `ps`, which macOS and Linux share."""
    try:
        p = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,rss="], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = []
    for line in p.stdout.splitlines():
        parts = line.split()
        if len(parts) == 4 and all(x.lstrip("-").isdigit() for x in parts):
            rows.append(tuple(int(x) for x in parts))
    return rows


def tree_of(root: int, table: list[tuple[int, int, int, int]] | None = None) -> set[int]:
    """`root`, its process group, and every descendant by parent link."""
    table = _ps_table() if table is None else table
    found = {root} | {pid for pid, _pp, pg, _r in table if pg == root}
    changed = True
    while changed:
        changed = False
        for pid, ppid, _pg, _r in table:
            if ppid in found and pid not in found:
                found.add(pid)
                changed = True
    return found


KILL_GRACE = 2.0   # seconds between SIGTERM and SIGKILL


def _kill_tree(proc) -> None:
    """SIGTERM to the group and every descendant, a short grace so test runners can clean
    up, then SIGKILL to whatever is left. The descendant set is taken while the parent is
    still alive — once it dies, its children are re-parented and the link is gone."""
    import os
    import signal
    import time
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        return
    pids = tree_of(proc.pid) - {os.getpid()}

    def send(sig) -> None:
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        for pid in pids:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    send(signal.SIGTERM)
    end = time.monotonic() + KILL_GRACE
    while time.monotonic() < end and proc.poll() is None:
        time.sleep(0.05)
    send(signal.SIGKILL)


def run_bounded(cmd, cwd: Path | str | None, timeout: float, *, shell: bool = False,
                env: dict | None = None, input_bytes: bytes | None = None,
                mem_limit: int | None = None) -> Bounded:
    """Run `cmd` (argv list, or a string with shell=True) with a hard wall-clock limit and a
    memory watchdog over its whole process tree; never leaves anything running behind it.
    returncode is -1 when the run was killed (see `.killed`). Raises OSError if it cannot start."""
    import time
    limit = mem_limit_mb() if mem_limit is None else mem_limit
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, cwd=None if cwd is None else str(cwd), env=env, shell=shell,
                            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    deadline = time.monotonic() + timeout
    killed, peak, out, err = "", 0, b"", b""
    first = True
    while True:
        try:
            out, err = proc.communicate(input=input_bytes if first else None,
                                        timeout=min(1.0, max(0.05, deadline - time.monotonic())))
            break
        except subprocess.TimeoutExpired:
            first = False
        if limit and sys.platform != "win32":
            table = _ps_table()
            members = tree_of(proc.pid, table)
            rss_mb = sum(r for pid, _pp, _pg, r in table if pid in members) // 1024
            peak = max(peak, rss_mb)
            if rss_mb > limit:
                killed = "memory"
        if not killed and time.monotonic() >= deadline:
            killed = "timeout"
        if killed:
            _kill_tree(proc)
            try:
                out, err = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                # something escaped the tree (a double-forked daemon) and still holds the
                # pipe: stop waiting rather than hang the caller on it
                proc.kill()
                for stream in (proc.stdout, proc.stderr):
                    try:
                        stream.close()
                    except (OSError, AttributeError):
                        pass
                proc.wait(timeout=5)
                out, err = b"", b"[crucible] output lost: a descendant escaped and held the pipe"
            break
    if not killed and sys.platform != "win32":
        import os
        import signal
        try:                  # whatever the command left running in its own group
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    text_out = (out or b"").decode("utf-8", "replace")
    text_err = (err or b"").decode("utf-8", "replace")
    if killed:
        why = (f"killed after {timeout:.0f}s" if killed == "timeout"
               else f"killed at {peak} MB resident (cap {limit} MB, CRUCIBLE_MEM_LIMIT_MB)")
        text_err += f"\n[crucible] {why} — the whole process tree was stopped\n"
    return Bounded(-1 if killed else proc.returncode, text_out, text_err, killed, peak)


# --------------------------------------------------------------------------- a pytest that runs
# `python3 -m pytest` is not a test run on a machine whose python3 has no pytest — and that
# is the default on a Homebrew Python. It exits 1, "No module named pytest", which reads as
# "the tests failed". Resolve an interpreter that can actually run the suite, in order: the
# repo's own virtualenv, the interpreter running this script, then `uv run --with pytest`.
# None means there is no way to run the tests here — a could-not-determine, not a failure.

def _venv_python(repo: Path) -> list[Path]:
    rel = ("Scripts/python.exe",) if sys.platform == "win32" else ("bin/python",)
    return [Path(repo) / v / r for v in (".venv", "venv") for r in rel]


def pytest_command(repo: Path) -> list[str] | None:
    candidates = [str(p) for p in _venv_python(repo) if p.exists()] + [python_exe()]
    for exe in candidates:
        rc, _ = run([exe, "-c", "import pytest"], Path(repo), timeout=60)
        if rc == 0:
            return [exe, "-m", "pytest"]
    if shutil.which("uv"):
        project = [] if (Path(repo) / "pyproject.toml").exists() else ["--no-project"]
        return ["uv", "run", "-q", *project, "--with", "pytest", "python", "-m", "pytest"]
    return None


def shell_join(argv: list[str]) -> str:
    if sys.platform == "win32":
        return subprocess.list2cmdline(argv)
    import shlex
    return shlex.join(argv)
