#!/usr/bin/env python3
"""Compare the SET of collected tests between a branch point and the working tree.

A passing-count comparison cannot see a suite that shrank: delete a test and add
another and the count is unchanged, delete a test and the suite stays green because
what would have failed is simply no longer asked. Counts answer "did anything break";
only the *set of test identities* answers "is anything no longer checked".

Deterministic and pure stdlib. Prints a report and exits:
    0 — no test disappeared
    1 — one or more tests present at BASE are gone (coverage regression)
    2 — could not determine (no git, no collector, collection failed)

Exit 2 is deliberately distinct: "I could not tell" must never read as "all clear".

Scope: compares collected test identities. It does NOT detect a test that still
collects but was neutered (assertions removed, or newly skipped at runtime) — those
need the assertion review in the gatekeeper's §4b, not this script.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_TARGETS = ("dev", "main", "master", "trunk")


def _run(cmd: list[str], cwd: Path, timeout: int = 300) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, f"{type(e).__name__}: {e}"
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def git_branches(repo: Path) -> list[str]:
    rc, out = _run(["git", "branch", "--format=%(refname:short)"], repo)
    return [b.strip() for b in out.splitlines() if b.strip()] if rc == 0 else []


def detect_target(repo: Path, preferred: str | None = None) -> str | None:
    """The long-lived branch this work integrates into."""
    branches = set(git_branches(repo))
    if preferred:
        return preferred if preferred in branches else None
    for name in DEFAULT_TARGETS:
        if name in branches:
            return name
    return None


def merge_base(repo: Path, target: str) -> str | None:
    rc, out = _run(["git", "merge-base", "HEAD", target], repo)
    return out.strip() if rc == 0 and out.strip() else None


def detect_collect_cmd(repo: Path) -> list[str] | None:
    """Pick a collector from marker files. Returns None rather than guessing — a wrong
    collector yields an empty set, which would silently look like 'everything was deleted'."""
    if any((repo / f).exists() for f in ("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")) \
            or (repo / "tests").is_dir():
        # `-o addopts=` clears the repo's configured addopts. Without it a repo that already
        # sets `addopts = -q` gets `-qq`, and pytest collapses collection to per-file counts
        # ("tests/test_x.py: 54") with no node IDs at all — which parses to an empty set and
        # would read as "every test was deleted", or worse, as a clean 0-vs-0 comparison.
        return ["python3", "-m", "pytest", "--collect-only", "-q",
                "-o", "addopts=", "-p", "no:cacheprovider"]
    return None


NODE_RE = re.compile(r"^(\S+::\S+)")


def parse_node_ids(text: str) -> set[str]:
    """Extract `path::test` identities from a collector's output."""
    ids = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("=", "-", "warning", "ERROR", "no tests ran")):
            continue
        m = NODE_RE.match(line)
        if m:
            ids.add(m.group(1))
    return ids


def collect_at(repo: Path, cmd: list[str]) -> set[str] | None:
    """Collect in `repo`. Returns None when collection could not be trusted."""
    rc, out = _run(cmd, repo)
    ids = parse_node_ids(out)
    # pytest exits 0 with tests, 5 when none were collected. Any other non-zero means the
    # collector itself failed (import error, bad config) and an empty/partial set from that
    # run must not be read as "these tests do not exist".
    if rc not in (0, 5):
        return None
    return ids


def collect_at_rev(repo: Path, rev: str, cmd: list[str]) -> set[str] | None:
    """Collect at `rev` in a throwaway worktree, leaving the working tree untouched."""
    tmp = Path(tempfile.mkdtemp(prefix="covdelta-"))
    wt = tmp / "wt"
    rc, out = _run(["git", "worktree", "add", "--detach", str(wt), rev], repo)
    if rc != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    try:
        return collect_at(wt, cmd)
    finally:
        _run(["git", "worktree", "remove", "--force", str(wt)], repo)
        shutil.rmtree(tmp, ignore_errors=True)


def report(base_ids: set[str], head_ids: set[str]) -> tuple[int, str]:
    removed = sorted(base_ids - head_ids)
    added = sorted(head_ids - base_ids)
    lines = [
        f"collected at BASE: {len(base_ids)}",
        f"collected at HEAD: {len(head_ids)}",
        f"added:   {len(added)}",
        f"removed: {len(removed)}",
    ]
    if added:
        lines.append("\nADDED:")
        lines += [f"  + {t}" for t in added]
    if removed:
        lines.append("\nREMOVED — these were checked at the branch point and are not any more:")
        lines += [f"  - {t}" for t in removed]
        lines.append(
            "\nCOVERAGE REGRESSION. A green suite does not cover this: what these tests "
            "asserted is simply no longer asked. Each removal needs an explicit reason "
            "(the behaviour was deliberately deleted, or the test moved and is listed under "
            "ADDED); otherwise REJECT."
        )
        return 1, "\n".join(lines)
    lines.append("\nOK — no test present at BASE disappeared.")
    return 0, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="repository path (default: cwd)")
    ap.add_argument("--target", default=None, help="integration branch (default: auto-detect)")
    ap.add_argument("--base", default=None, help="explicit base revision (skips merge-base)")
    ap.add_argument("--collect-cmd", default=None,
                    help="collector command, e.g. \"npx vitest list\" (default: auto-detect pytest)")
    a = ap.parse_args(argv)

    repo = Path(a.repo).resolve()
    if not (repo / ".git").exists():
        rc, _ = _run(["git", "rev-parse", "--git-dir"], repo)
        if rc != 0:
            print(f"cannot determine coverage delta: {repo} is not a git repository", file=sys.stderr)
            return 2

    base = a.base
    if not base:
        target = detect_target(repo, a.target)
        if not target:
            print("cannot determine coverage delta: no integration branch found "
                  f"(looked for {', '.join(DEFAULT_TARGETS)}); pass --target or --base", file=sys.stderr)
            return 2
        base = merge_base(repo, target)
        if not base:
            print(f"cannot determine coverage delta: no merge-base with '{target}'", file=sys.stderr)
            return 2

    cmd = a.collect_cmd.split() if a.collect_cmd else detect_collect_cmd(repo)
    if not cmd:
        print("cannot determine coverage delta: no test collector detected; pass --collect-cmd",
              file=sys.stderr)
        return 2

    head_ids = collect_at(repo, cmd)
    if head_ids is None:
        print("cannot determine coverage delta: collection failed on the working tree", file=sys.stderr)
        return 2
    base_ids = collect_at_rev(repo, base, cmd)
    if base_ids is None:
        print(f"cannot determine coverage delta: collection failed at BASE ({base[:12]})", file=sys.stderr)
        return 2

    if not base_ids and not head_ids:
        # Zero on both sides is not "nothing was removed" — it is almost always a collector
        # that produced no node IDs (wrong command, doubled -q, wrong rootdir). Reporting OK
        # here would turn a broken check into a clean bill of health, which is the exact
        # failure this script exists to catch.
        print("cannot determine coverage delta: collected 0 tests at BASE and 0 at HEAD — "
              "the collector produced no test IDs. Check --collect-cmd.", file=sys.stderr)
        return 2

    code, text = report(base_ids, head_ids)
    print(f"BASE = {base[:12]}\n{text}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
