#!/usr/bin/env python3
"""How old is a document, answered in a way that survives `git clone`. Pure stdlib.

The archive rule asks "has anyone touched this in 60 days?". It used to answer with
`path.stat().st_mtime`, which does not answer that question at all: git does not record
or restore mtimes, so a fresh clone stamps every file with the checkout time and every
document in the repository reads as zero days old. The rule silently stopped firing on
CI, on a new machine, and for any consumer who cloned rather than copied — while looking
entirely healthy, because "no findings" is also what a clean repo looks like.

`render.py` learned this already (see its content-hash staleness check, whose docstring
notes the same failure "fired on the first merge of this tool"). This module back-ports
the lesson to the four sites that still trusted mtime.

Resolution order, and the one rule that matters:

  1. **git committer date** (`%ct`) — ground truth for "when did this content last
     change", batched into a single `git log` pass for the whole repository.
  2. **frontmatter** — `last_reviewed_on`, then `created`. Clone-stable by construction,
     because it is file content, and already required on every `docs/*` file.
  3. **unknown** — and unknown means *emit nothing*. It never falls back to mtime.

Committer date, not author date, is deliberate. Both can be wrong, but the failure modes
are opposite: author date survives a rebase and so reports a file as older than history
actually shows, while committer date is rewritten and so reports it as younger.
Under-reporting age is the safe direction for a rule whose action is "archive this".
`%ct` is epoch seconds, which sidesteps timezone parsing entirely.

Three git subtleties this depends on, each of which silently corrupts the answer:

- **Merges print no filenames by default.** Without `--diff-merges=first-parent`, a file
  whose only change arrived through a squash-merge is invisible to `--name-only` and
  reads as never having been touched.
- **Output order is not reliably monotonic**, so the per-path timestamp is a max() over
  every commit that mentions it, not "the first one seen".
- **A shallow clone is the trap.** With depth=1 every path collapses onto the graft
  commit, so every file reads as changed today — the same failure as mtime, except now
  invisible, because it looks like a legitimate git date. We detect it and refuse to
  answer rather than answering wrongly.

No pathspec is passed to `git log`. Restricting it (`-- docs/`) turns on history
simplification, which prunes side-branch commits and can make a file look *older* than
it is; `--full-history` undoes that bias but costs more than the pathspec saves.
"""
from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from common import parse_frontmatter, parse_iso_date

# How long a completion artifact sits before it becomes an archive candidate. Single
# source of truth: check.py and migrate.py each used to carry their own copy of this
# number, and their own copy of the rule around it.
ARCHIVE_AGE_DAYS = 60

GIT_TIMEOUT_SECONDS = 60

SOURCE_GIT = "git"
SOURCE_FRONTMATTER = "frontmatter"
SOURCE_WORKING_TREE = "working tree"
SOURCE_UNKNOWN = "unknown"


def _run_git(args: list, cwd: Path) -> Optional[str]:
    """Run a git command, returning stdout, or None if it could not be run at all.

    Encoding is pinned at both ends: `text=True` alone decodes with the locale, which is
    cp1252 on many Windows installs and mangles any non-ASCII path.
    """
    try:
        proc = subprocess.run(
            ["git"] + list(args),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None  # git absent, or it hung past the timeout
    if proc.returncode != 0:
        return None
    return proc.stdout


class RepoDates:
    """Committer dates for every tracked path in one repository, from one `git log`.

    Built eagerly on construction and cached per repository. The alternative — one
    `git log -1 -- <path>` per file — is worse than O(n) process spawns, because each
    invocation walks history from HEAD until it finds a commit touching that path.
    """

    def __init__(self, repo_root: Path, available: bool, reason: str = "") -> None:
        self.repo_root = repo_root
        self.available = available
        self.reason = reason
        self.last = {}      # posix relpath -> date of the newest commit touching it
        self.first = {}     # posix relpath -> date of the oldest commit touching it
        self.pending = set()  # untracked or modified — age 0, never a candidate
        if available:
            self._load_pending()
            self._load_log()

    def _load_pending(self) -> None:
        """Paths carrying uncommitted state. Their git date describes an older version of
        a file that has since been edited, so treating them as freshly touched is both
        the honest answer and the safe one."""
        out = _run_git(["status", "--porcelain", "-z"], self.repo_root)
        if not out:
            return
        for entry in out.split("\0"):
            if len(entry) > 3:
                self.pending.add(entry[3:].replace("\\", "/"))

    def _load_log(self) -> None:
        base = ["-c", "core.quotePath=false", "log", "--format=%x00%ct",
                "--name-only", "--no-renames"]
        out = _run_git(base + ["--diff-merges=first-parent"], self.repo_root)
        if out is None:
            # `--diff-merges=first-parent` needs git 2.31+. Without it, a file whose only
            # change arrived via a merge is invisible — degraded, but better than silence.
            out = _run_git(base, self.repo_root)
        if out is None:
            self.available = False
            self.reason = "`git log` could not be read"
            return
        current = None
        for line in out.splitlines():
            if line.startswith("\0"):
                current = _epoch_to_date(line[1:].strip())
                continue
            rel = line.strip()
            if not rel or current is None:
                continue
            rel = rel.replace("\\", "/")
            # max for "last changed", min for "created" — one pass, both answers.
            known = self.last.get(rel)
            if known is None or current > known:
                self.last[rel] = current
            known = self.first.get(rel)
            if known is None or current < known:
                self.first[rel] = current

    def relative(self, path: Path) -> Optional[str]:
        try:
            return path.resolve().relative_to(self.repo_root).as_posix()
        except ValueError:
            return None  # outside this repository


def _epoch_to_date(stamp: str) -> Optional[date]:
    try:
        return datetime.fromtimestamp(int(stamp), tz=timezone.utc).date()
    except (ValueError, OverflowError, OSError):
        return None


_REPO_BY_DIR = {}
_DATES_BY_ROOT = {}


def clear_cache() -> None:
    """Drop the memoized git state. For tests, which build a fresh repo per case."""
    _REPO_BY_DIR.clear()
    _DATES_BY_ROOT.clear()


def _repo_root_for(path: Path) -> Optional[Path]:
    start = path if path.is_dir() else path.parent
    key = str(start.resolve())
    if key in _REPO_BY_DIR:
        return _REPO_BY_DIR[key]
    root = None
    if start.exists():
        out = _run_git(["rev-parse", "--show-toplevel"], start)
        if out and out.strip():
            root = Path(out.strip()).resolve()
    _REPO_BY_DIR[key] = root
    return root


def repo_dates(path: Path) -> Optional[RepoDates]:
    """Return the cached git dates for the repository containing `path`, or None."""
    root = _repo_root_for(path)
    if root is None:
        return None
    key = str(root)
    if key not in _DATES_BY_ROOT:
        shallow = _run_git(["rev-parse", "--is-shallow-repository"], root)
        if shallow is not None and shallow.strip() == "true":
            _DATES_BY_ROOT[key] = RepoDates(
                root, False,
                "shallow clone — every path collapses onto the graft commit, so every "
                "document would read as changed today. Clone with full history "
                "(`fetch-depth: 0` on actions/checkout) to restore the age check.")
        else:
            _DATES_BY_ROOT[key] = RepoDates(root, True)
    return _DATES_BY_ROOT[key]


def age_source_status(repo: Path) -> tuple:
    """(is the git age source usable here, why not) — for a one-time repo-level report."""
    dates = repo_dates(repo)
    if dates is None:
        return False, ("not a git repository — document age falls back to frontmatter "
                       "dates, and files without frontmatter get no age check at all")
    if not dates.available:
        return False, dates.reason
    return True, ""


def _frontmatter_date(path: Path, text: Optional[str]) -> Optional[date]:
    if text is None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    fm, _ = parse_frontmatter(text)
    for field in ("last_reviewed_on", "created"):
        parsed = parse_iso_date(fm.get(field, ""))
        if parsed:
            return parsed
    return None


def last_changed(path: Path, text: Optional[str] = None) -> tuple:
    """When this document last changed, and which source said so.

    Returns `(None, SOURCE_UNKNOWN)` when nothing clone-stable can answer. Callers must
    treat that as "do not report" — never as "old", never as "new". A guess here is
    exactly the bug this module exists to remove.
    """
    dates = repo_dates(path)
    if dates is not None and dates.available:
        rel = dates.relative(path)
        if rel is not None:
            if rel in dates.pending:
                return date.today(), SOURCE_WORKING_TREE
            found = dates.last.get(rel)
            if found is not None:
                return found, SOURCE_GIT
    fm_date = _frontmatter_date(path, text)
    if fm_date is not None:
        return fm_date, SOURCE_FRONTMATTER
    return None, SOURCE_UNKNOWN


def first_committed(path: Path, text: Optional[str] = None) -> tuple:
    """When this document first entered history — the honest value for `created:`."""
    dates = repo_dates(path)
    if dates is not None and dates.available:
        rel = dates.relative(path)
        if rel is not None:
            found = dates.first.get(rel)
            if found is not None:
                return found, SOURCE_GIT
    fm_date = _frontmatter_date(path, text)
    if fm_date is not None:
        return fm_date, SOURCE_FRONTMATTER
    return None, SOURCE_UNKNOWN


def age_days(path: Path, text: Optional[str] = None) -> tuple:
    """(days since last change, that date, source). Days is None when unknown."""
    changed, source = last_changed(path, text)
    if changed is None:
        return None, None, source
    return (date.today() - changed).days, changed, source


def main(argv: Optional[list] = None) -> int:
    """Report the resolved age and source for each path given — the debugging entry point
    for "why is this file (not) an archive candidate?"."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: doc_age.py <path> [<path> ...]", file=sys.stderr)
        return 2
    for raw in args:
        path = Path(raw).expanduser()
        days, changed, source = age_days(path)
        if days is None:
            print(f"{path.as_posix()}: age unknown (source: {source})")
        else:
            print(f"{path.as_posix()}: {changed} ({days} days ago) via {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
