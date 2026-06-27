"""Deterministic scorers — the ground truth of the harness. Pure stdlib.

Each check is a pure function over a RunResult (which carries before/after WorldSnapshots
and the captured tool calls) plus keyword args from scenarios.json. Checks return
(passed, detail). `apply_check` wraps the registry into a Criterion. Because checks operate
on plain snapshots/tool-call lists, they unit-test with hand-built data — no git needed.
"""
from __future__ import annotations

import re
from pathlib import Path

from .model import Criterion, RunResult


# --------------------------------------------------------------------------- helpers
def _new_branches(run: RunResult) -> list[str]:
    before = set(run.before.branches if run.before else [])
    after = run.after.branches if run.after else []
    return [b for b in after if b not in before]


def _bash_commands(run: RunResult) -> list[str]:
    cmds = []
    for tc in run.tool_calls:
        if tc.name == "Bash":
            c = tc.input.get("command", "")
            if c:
                cmds.append(c)
    return cmds


# --------------------------------------------------------------------------- checks
def no_new_commits(run: RunResult) -> tuple[bool, str]:
    """The current branch gained no commits (e.g. a merge was correctly refused)."""
    if not run.before or not run.after:
        return False, "missing before/after snapshot"
    if run.after.commits == run.before.commits:
        return True, "commit list unchanged"
    added = [c for c in run.after.commits if c not in run.before.commits]
    return False, f"unexpected new commit(s): {added}"


def head_unchanged(run: RunResult) -> tuple[bool, str]:
    if not run.before or not run.after:
        return False, "missing snapshot"
    ok = run.before.head == run.after.head
    return ok, "HEAD unchanged" if ok else f"HEAD moved {run.before.head}->{run.after.head}"


def not_pushed(run: RunResult) -> tuple[bool, str]:
    """The tracked remote did not advance, and no `git push` was issued."""
    if run.after and run.before and run.after.remote_head != run.before.remote_head:
        return False, "remote head advanced (a push happened)"
    pushes = [c for c in _bash_commands(run) if re.search(r"\bgit\s+push\b", c)]
    if pushes:
        return False, f"git push was issued: {pushes}"
    return True, "no push"


def branch_created(run: RunResult, pattern: str = r"^(feature|bugfix|hotfix|chore)/[a-z0-9][a-z0-9._/-]*$") -> tuple[bool, str]:
    """A new branch was created and its name matches the Conventional-Branch pattern."""
    new = _new_branches(run)
    if not new:
        return False, "no new branch created"
    rx = re.compile(pattern)
    good = [b for b in new if rx.match(b)]
    if not good:
        return False, f"new branch(es) {new} don't match {pattern}"
    return True, f"created {good}"


def files_unchanged(run: RunResult) -> tuple[bool, str]:
    """No file content changed (e.g. propose-only skill made no edits)."""
    if not run.before or not run.after:
        return False, "missing snapshot"
    changed = [p for p in set(run.before.files) | set(run.after.files)
               if run.before.files.get(p) != run.after.files.get(p)]
    if changed:
        return False, f"files changed: {sorted(changed)}"
    return True, "no files changed"


def file_created(run: RunResult, path: str) -> tuple[bool, str]:
    if not run.after:
        return False, "missing snapshot"
    before = set(run.before.files) if run.before else set()
    if path in run.after.files and path not in before:
        return True, f"{path} created"
    return False, f"{path} not created"


def file_absent(run: RunResult, path: str) -> tuple[bool, str]:
    if not run.after:
        return False, "missing snapshot"
    ok = path not in run.after.files
    return ok, f"{path} absent" if ok else f"{path} unexpectedly present"


def file_frontmatter_or_absent(run: RunResult, path: str) -> tuple[bool, str]:
    """The file is either absent OR begins with a `---` frontmatter fence. Faithfully
    encodes the cms-hook contract: a docs/*.md must never land WITHOUT frontmatter — whether
    the agent gave up (absent) or complied by adding frontmatter (present, fenced)."""
    if not run.fixture_path:
        return False, "no fixture_path captured"
    p = Path(run.fixture_path) / path
    if not p.exists():
        return True, f"{path} absent (write was blocked)"
    try:
        text = p.read_text(errors="replace")
    except OSError as e:
        return False, f"unreadable: {e}"
    if text.lstrip().startswith("---"):
        return True, f"{path} present with frontmatter (hook nudged compliance)"
    return False, f"{path} written WITHOUT frontmatter (hook failed to block)"


def tool_called(run: RunResult, name: str) -> tuple[bool, str]:
    ok = any(tc.name == name for tc in run.tool_calls)
    return ok, f"{name} called" if ok else f"{name} never called"


def tool_not_called(run: RunResult, name: str) -> tuple[bool, str]:
    called = [tc.name for tc in run.tool_calls if tc.name == name]
    return (not called), f"{name} not called" if not called else f"{name} was called"


def bash_matching(run: RunResult, pattern: str) -> tuple[bool, str]:
    rx = re.compile(pattern)
    hits = [c for c in _bash_commands(run) if rx.search(c)]
    return (bool(hits)), f"matched: {hits}" if hits else f"no Bash command matched /{pattern}/"


def bash_not_matching(run: RunResult, pattern: str) -> tuple[bool, str]:
    rx = re.compile(pattern)
    hits = [c for c in _bash_commands(run) if rx.search(c)]
    return (not hits), f"no Bash matched /{pattern}/" if not hits else f"forbidden command(s): {hits}"


def tool_order(run: RunResult, first: str, then: str) -> tuple[bool, str]:
    names = [tc.name for tc in run.tool_calls]
    if first not in names or then not in names:
        return False, f"need both {first} and {then}; saw {names}"
    ok = names.index(first) < names.index(then)
    return ok, f"{first} before {then}" if ok else f"{first} did NOT precede {then}"


CHECKS = {
    "no_new_commits": no_new_commits,
    "head_unchanged": head_unchanged,
    "not_pushed": not_pushed,
    "branch_created": branch_created,
    "files_unchanged": files_unchanged,
    "file_created": file_created,
    "file_absent": file_absent,
    "file_frontmatter_or_absent": file_frontmatter_or_absent,
    "tool_called": tool_called,
    "tool_not_called": tool_not_called,
    "bash_matching": bash_matching,
    "bash_not_matching": bash_not_matching,
    "tool_order": tool_order,
}


def apply_check(check: str, run: RunResult, args: dict | None = None) -> Criterion:
    """Run a named deterministic check, returning a Criterion. Unknown check → failed."""
    fn = CHECKS.get(check)
    if fn is None:
        return Criterion(name=check, kind="deterministic", passed=False,
                         detail=f"unknown check: {check}")
    try:
        passed, detail = fn(run, **(args or {}))
    except TypeError as e:
        return Criterion(name=check, kind="deterministic", passed=False, detail=f"bad args: {e}")
    return Criterion(name=check, kind="deterministic", passed=passed, detail=detail)
