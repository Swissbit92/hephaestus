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
    remote_head = _git(repo, "rev-parse", f"origin/{branch}") or None
    return WorldSnapshot(
        branch=branch, head=head, commits=commits, dirty=dirty,
        branches=branches, remote_head=remote_head, files=_hash_files(repo),
    )
