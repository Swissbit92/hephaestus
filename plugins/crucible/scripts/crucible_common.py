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
