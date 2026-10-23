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
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, f"{type(e).__name__}: {e}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


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
