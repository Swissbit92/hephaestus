#!/usr/bin/env python3
"""Run the checks wired to a repository's standing invariants.

An invariant is a constraint that outlives every task: "mobile-first", "no new
dependencies", "stays backward compatible". They are stated once, early, and then compete
for attention with everything said since — so by the time they are about to be violated,
they are the oldest and least salient thing in the conversation. Restating them louder does
not fix that; the mechanism that forgets is the same one being asked to remember.

So this does not remind anyone of anything. It reads `docs/INVARIANTS.md`, finds the
entries that have an executable check wired to them, and runs those checks. A script does
not care how long ago the constraint was written.

Its honesty rests on distinguishing three different silences: no invariants file, a file
whose entries have no checks yet, and checks that ran and passed. Only the last is evidence.

Format expected in docs/INVARIANTS.md — one entry per `##` heading:

    ## Mobile-first layout
    Status: active
    Statement: The UI is usable at phone width before desktop width.
    Falsifiable: WHEN the viewport is 375px wide THE SYSTEM SHALL NOT scroll horizontally.
    Check: scripts/checks/no_horizontal_scroll.sh

`Check: none yet` (or a missing field) means stated but not yet enforceable.

Exit codes:
    0 — every wired check ran and passed
    1 — an active invariant's check FAILED (a violation)
    2 — could not determine (a Check: path missing or not executable, or a parse failure)
    3 — nothing enforceable: no INVARIANTS.md, or no entry has a check yet. NOT a pass.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_REL = "docs/INVARIANTS.md"
_FIELD = re.compile(r"^(Status|Statement|Falsifiable|Check)\s*:\s*(.*)$", re.I)
_NONE = {"", "none", "none yet", "todo", "tbd", "-", "n/a"}


class Entry:
    __slots__ = ("title", "status", "statement", "falsifiable", "check")

    def __init__(self, title: str) -> None:
        self.title = title
        self.status = "active"
        self.statement = ""
        self.falsifiable = ""
        self.check = ""

    @property
    def is_active(self) -> bool:
        return self.status.strip().lower() == "active"

    @property
    def has_check(self) -> bool:
        return self.check.strip().lower() not in _NONE

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Entry({self.title!r}, status={self.status!r}, check={self.check!r})"


def parse(text: str) -> list[Entry]:
    """Entries keyed by `##` headings. Unknown lines are ignored so the file stays a
    document a human wants to read, not a config format they have to appease."""
    entries: list[Entry] = []
    current: Entry | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            current = Entry(stripped[3:].strip())
            entries.append(current)
            continue
        if current is None:
            continue
        m = _FIELD.match(stripped)
        if m:
            key, val = m.group(1).lower(), m.group(2).strip()
            setattr(current, "statement" if key == "statement" else key, val)
    return entries


def run_check(repo: Path, entry: Entry, timeout: int = 300) -> tuple[int, str]:
    """(exit_code, detail). Code 2 means the check could not be run at all — which is not
    the same as the invariant holding, and must not be reported as though it were."""
    raw = entry.check.strip()
    parts = raw.split()
    target = repo / parts[0]
    if not target.exists():
        return 2, f"Check path does not exist: {parts[0]}"
    cmd: list[str]
    if target.suffix == ".py":
        cmd = [sys.executable, str(target), *parts[1:]]
    elif target.suffix in (".sh", ""):
        cmd = ["sh", str(target), *parts[1:]]
    else:
        cmd = [str(target), *parts[1:]]
    try:
        p = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 2, f"could not execute: {type(e).__name__}: {e}"
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    return p.returncode, out.splitlines()[-1] if out else ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="repository path (default: cwd)")
    ap.add_argument("--file", default=DEFAULT_REL, help=f"invariants file (default: {DEFAULT_REL})")
    ap.add_argument("--timeout", type=int, default=300, help="per-check timeout in seconds")
    a = ap.parse_args(argv)

    repo = Path(a.repo).resolve()
    path = repo / a.file
    if not path.exists():
        print(f"no invariants file at {a.file} — nothing enforceable.\n"
              "This is a SKIP, not a pass: no constraint was checked.", file=sys.stderr)
        return 3
    try:
        entries = parse(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as e:
        print(f"cannot determine: unreadable {a.file}: {e}", file=sys.stderr)
        return 2

    active = [e for e in entries if e.is_active]
    wired = [e for e in active if e.has_check]
    if not wired:
        print(f"{len(active)} active invariant(s), none with a Check: yet — nothing to run.\n"
              "This is a SKIP, not a pass. An invariant with no executable check is a wish; "
              "it is stated but nothing prevents its violation.", file=sys.stderr)
        return 3

    failures, undetermined, passed = [], [], []
    for e in wired:
        code, detail = run_check(repo, e, a.timeout)
        if code == 0:
            passed.append(e)
            print(f"  ok    {e.title}")
        elif code == 2 and detail.startswith(("Check path does not exist", "could not execute")):
            undetermined.append((e, detail))
            print(f"  ????  {e.title} — {detail}")
        else:
            failures.append((e, detail))
            print(f"  FAIL  {e.title} — {detail}")

    skipped = len(active) - len(wired)
    print(f"\n{len(passed)} passed, {len(failures)} failed, {len(undetermined)} undetermined, "
          f"{skipped} active without a check")

    if failures:
        print("\nINVARIANT VIOLATED. These constraints were agreed to hold for all work in "
              "this repository, and the check says they no longer do:", file=sys.stderr)
        for e, detail in failures:
            print(f"  - {e.title}: {e.falsifiable or e.statement or '(no statement)'}",
                  file=sys.stderr)
        return 1
    if undetermined:
        print("\ncannot determine: a wired check could not be run. Not a pass — fix the "
              "Check: path and re-run.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
