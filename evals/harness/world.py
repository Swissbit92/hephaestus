"""Capture a fixture's git + file state into a WorldSnapshot. Live (runs `git`), but uses
only stdlib + the git CLI, so it's exercised by unit tests against real temp repos."""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from .model import WorldSnapshot

_SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip() if r.returncode == 0 else ""


def _hash_files(repo: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for p in sorted(repo.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(repo)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        try:
            files[rel.as_posix()] = hashlib.sha1(p.read_bytes()).hexdigest()
        except OSError:
            files[rel.as_posix()] = "<unreadable>"
    return files


def snapshot(repo: Path | str) -> WorldSnapshot:
    repo = Path(repo)
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    head = _git(repo, "rev-parse", "HEAD")
    commits = [c for c in _git(repo, "log", "--pretty=%s", "-n", "50").splitlines() if c]
    dirty = bool(_git(repo, "status", "--porcelain"))
    branches = [b for b in _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines() if b]
    return WorldSnapshot(
        branch=branch, head=head, commits=commits, dirty=dirty,
        branches=branches, remote_state=_remote_state(repo), files=_hash_files(repo),
    )


def _remote_state(repo: Path) -> str | None:
    """A digest of every ref on the ACTUAL remote, or None when there is no remote.

    This used to be `rev-parse origin/<current-branch>`, and that was wrong twice over.

    First, it read a *remote-tracking* ref — a local pointer git moves during any network
    communication, including a plain `git fetch`. Tracking refs therefore cannot tell a
    fetch from a push, which is the only distinction this snapshot exists to make.

    Second, and worse, it interpolated the branch that happened to be checked out *at
    snapshot time*. A scenario that creates and checks out a branch — which is precisely
    what `start-branch` is for — captured `origin/main` before and `origin/<new-branch>`
    after. The second ref does not exist, so the comparison was `sha != None` and every
    such run was reported as "a push happened". `start-branch/refetches-before-branching`
    failed five times out of five on behaviour that was entirely correct, and the failure
    was reproducible enough to look like a real defect.

    `git ls-remote` asks the remote itself, so it is immune to both: branch changes cannot
    move it, fetches cannot move it, and only a real push can.
    """
    refs = _git(repo, "ls-remote", "origin")
    return hashlib.sha1(refs.encode("utf-8")).hexdigest() if refs else None
