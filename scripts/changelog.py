#!/usr/bin/env python3
"""Cut, archive and size-check the long-lived history docs. Pure stdlib.

Why this exists: CHANGELOG.md is a single root file for every plugin. Nothing ever moved
`[Unreleased]` under a version heading after 0.6.3, so 115 KB of released work sat under
one heading and no size rule could cut it. This script makes the cut a command, makes
`release.sh` refuse to tag without it, and archives old entries into `docs/archive/`
(moved, never deleted: git keeps the history and the archive keeps the text).

Usage (run from the repo root; `--root` overrides):
    changelog.py cut <plugin> <version> [--date YYYY-MM-DD]   move [Unreleased] under
                                                              `## [<plugin>-v<version>] — date`
    changelog.py check <plugin> <version> [--cuttable]        exit 0 if that heading exists
                                                              (--cuttable: or [Unreleased] can be cut)
    changelog.py archive [--keep 5] [--apply]                 move versions beyond the newest N
    changelog.py archive-lessons [--days 60] [--keep 3] [--apply]
    changelog.py report                                       sizes, ARCHIVE DUE, removal candidates

`archive*` are dry runs unless `--apply`. Ages come from the date written in an entry's own
heading, never from a file's mtime. Exit: 0 ok · 1 refused (empty/duplicate/missing) · 2 usage.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Tuple

CHANGELOG = "CHANGELOG.md"
LESSONS = "docs/LESSONS_LEARNED.md"
ROADMAP = "docs/ROADMAP.md"
ARCHIVE_DIR = "docs/archive"

# One source of truth for the limits; cms's check_doc_budgets mirrors them and a test
# asserts the two agree.
CHANGELOG_MAX_BYTES = 40_000
LESSONS_MAX_BYTES = 25_000
KEEP_VERSIONS = 5
LESSONS_AGE_DAYS = 60
LESSONS_KEEP_NEWEST = 3

POINTER_CHANGELOG = "> Older releases are archived: see the `CHANGELOG.md` files under [docs/archive/](docs/archive/)."
POINTER_LESSONS = "> Older entries are archived: see the `LESSONS_LEARNED.md` files under [docs/archive/](docs/archive/)."

_REPO_METRICS = "plugins/crucible/skills/repo-audit/scripts/repo_metrics.py"
_VERSION_HEAD = re.compile(r"^## \[(?P<name>[^\]]+)\](?: — (?P<date>\d{4}-\d{2}-\d{2}))?\s*$")
_LESSON_HEAD = re.compile(r"^## (?P<date>\d{4}-\d{2}-\d{2}) — ")


class ChangelogError(Exception):
    """A refusal the caller should show as-is (exit 1)."""


Section = Tuple[str, str]  # (heading line, body text up to the next `## ` heading)


def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def split_sections(text: str) -> Tuple[str, List[Section]]:
    """Split on top-level `## ` headings, ignoring any inside a code fence."""
    preamble: List[str] = []
    sections: List[List[str]] = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            sections.append([line])
        elif sections:
            sections[-1].append(line)
        else:
            preamble.append(line)
    return "".join(preamble), [(s[0], "".join(s[1:])) for s in sections]


def join_sections(preamble: str, sections: List[Section]) -> str:
    return preamble + "".join(head + body for head, body in sections)


def _name(head: str) -> Optional[str]:
    m = _VERSION_HEAD.match(head.rstrip("\n"))
    return m.group("name") if m else None


def has_release(text: str, tag: str) -> bool:
    return any(_name(h) == tag for h, _ in split_sections(text)[1])


def cuttable(text: str) -> bool:
    """True when `[Unreleased]` exists and has something in it to move."""
    return any(_name(h) == "Unreleased" and b.strip() for h, b in split_sections(text)[1])


def cut(text: str, tag: str, on: str) -> str:
    """Move `[Unreleased]` under `## [tag] — on`; leave a fresh empty `[Unreleased]`."""
    preamble, sections = split_sections(text)
    if any(_name(h) == tag for h, _ in sections):
        raise ChangelogError(f"CHANGELOG already has a heading for [{tag}]")
    idx = next((i for i, (h, _) in enumerate(sections) if _name(h) == "Unreleased"), None)
    if idx is None:
        raise ChangelogError("CHANGELOG has no `## [Unreleased]` section to cut")
    body = sections[idx][1]
    if not body.strip():
        raise ChangelogError(
            "[Unreleased] is empty: write this release's changelog entry before cutting it")
    released = (f"## [{tag}] — {on}\n", body if body.endswith("\n\n") else body.rstrip("\n") + "\n\n")
    fresh = (sections[idx][0], "\n")
    return join_sections(preamble, sections[:idx] + [fresh, released] + sections[idx + 1:])


def _add_pointer(text: str, pointer: str) -> str:
    if pointer in text:
        return text
    return text.rstrip("\n") + "\n\n" + pointer + "\n"


def _strip_pointer(body: str, pointer: str) -> str:
    return body.replace(pointer + "\n", "").rstrip("\n") + "\n\n" if pointer in body else body


def _merge_archive(existing: Optional[str], title: str, intro: str, moved: str) -> str:
    """Put newly moved (newer) sections ahead of what the archive file already holds."""
    if not existing:
        return f"{title}\n\n{intro}\n\n{moved.rstrip(chr(10))}\n"
    pre, secs = split_sections(existing)
    return pre.rstrip("\n") + "\n\n" + moved.rstrip("\n") + "\n\n" + "".join(h + b for h, b in secs).lstrip("\n")


def archive_changelog(text: str, keep: int, on: str) -> Tuple[str, str, int]:
    """Return (new CHANGELOG text, moved sections text, number of versions moved)."""
    preamble, sections = split_sections(text)
    versions = [i for i, (h, _) in enumerate(sections) if _name(h) not in (None, "Unreleased")]
    move_idx = set(versions[keep:])
    if not move_idx:
        return text, "", 0
    moved = [sections[i] for i in sorted(move_idx)]
    kept = [s for i, s in enumerate(sections) if i not in move_idx]
    h, b = kept[-1]
    kept[-1] = (h, _strip_pointer(b, POINTER_CHANGELOG))
    return (_add_pointer(join_sections(preamble, kept), POINTER_CHANGELOG),
            "".join(h + b for h, b in moved), len(moved))


def _lesson_date(head: str) -> Optional[date]:
    m = _LESSON_HEAD.match(head)
    return datetime.strptime(m.group("date"), "%Y-%m-%d").date() if m else None


def archive_lessons(text: str, today: date, days: int, keep: int) -> Tuple[str, str, int]:
    """Move dated entries older than `days` (never the newest `keep`) out of the file."""
    preamble, sections = split_sections(text)
    dated = [i for i, (h, _) in enumerate(sections) if _lesson_date(h)]
    protected = set(sorted(dated, key=lambda i: _lesson_date(sections[i][0]), reverse=True)[:keep])
    move_idx = [i for i in dated if i not in protected
                and (today - _lesson_date(sections[i][0])).days > days]
    if not move_idx:
        return text, "", 0
    moved = [sections[i] for i in move_idx]
    kept = [s for i, s in enumerate(sections) if i not in set(move_idx)]
    h, b = kept[-1]
    kept[-1] = (h, _strip_pointer(b, POINTER_LESSONS))
    return (_add_pointer(join_sections(preamble, kept), POINTER_LESSONS),
            "".join(h + b for h, b in moved), len(moved))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _archive_path(root: Path, on: str, name: str) -> Path:
    return root / ARCHIVE_DIR / on[:7] / name


def lessons_due(text: str, today: date) -> int:
    return archive_lessons(text, today, LESSONS_AGE_DAYS, LESSONS_KEEP_NEWEST)[2]


def _dead_modules(root: Path) -> Optional[List[str]]:
    script = root / _REPO_METRICS
    if not script.is_file():
        return None
    try:
        out = subprocess.run([sys.executable, str(script), str(root)], capture_output=True,
                             text=True, encoding="utf-8", timeout=120, check=True).stdout
        return list(json.loads(out).get("dead_module_candidates", []))
    except (subprocess.SubprocessError, OSError, ValueError):
        return None


def report(root: Path, today: date) -> List[str]:
    lines = ["DOCS REPORT (sizes in bytes; nothing is changed or deleted)"]
    due = []
    for rel, limit in ((CHANGELOG, CHANGELOG_MAX_BYTES), (LESSONS, LESSONS_MAX_BYTES), (ROADMAP, None)):
        p = root / rel
        if not p.is_file():
            continue
        size = p.stat().st_size
        cap = f" (limit {limit:,})" if limit else ""
        lines.append(f"  {rel}: {size:,}{cap}")
        if rel == CHANGELOG and size > CHANGELOG_MAX_BYTES:
            due.append(f"ARCHIVE DUE: {rel} is {size:,} bytes (limit {limit:,}): "
                       f"run `scripts/changelog.py archive --apply`")
        if rel == LESSONS and size > LESSONS_MAX_BYTES and lessons_due(_read(p), today):
            due.append(f"ARCHIVE DUE: {rel} is {size:,} bytes (limit {limit:,}) and has entries "
                       f"older than {LESSONS_AGE_DAYS} days: run `scripts/changelog.py archive-lessons --apply`")
    lines += due or ["  no archive due"]
    dead = _dead_modules(root)
    if dead is None:
        lines.append("  removal candidates: unavailable (repo_metrics.py missing or failed)")
    else:
        lines.append(f"  removal candidates (name-based, low confidence; a human decides, "
                     f"each removal PR states its reason): {len(dead)}")
        lines += [f"    {d}" for d in dead[:10]]
        if len(dead) > 10:
            lines.append(f"    ... and {len(dead) - 10} more")
    return lines


def _today(arg: Optional[str]) -> date:
    return datetime.strptime(arg, "%Y-%m-%d").date() if arg else date.today()


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_stdio()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=".")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cut"); c.add_argument("plugin"); c.add_argument("version"); c.add_argument("--date")
    k = sub.add_parser("check"); k.add_argument("plugin"); k.add_argument("version")
    k.add_argument("--cuttable", action="store_true")
    a = sub.add_parser("archive"); a.add_argument("--keep", type=int, default=KEEP_VERSIONS)
    a.add_argument("--date"); a.add_argument("--apply", action="store_true")
    la = sub.add_parser("archive-lessons"); la.add_argument("--days", type=int, default=LESSONS_AGE_DAYS)
    la.add_argument("--keep", type=int, default=LESSONS_KEEP_NEWEST)
    la.add_argument("--date"); la.add_argument("--apply", action="store_true")
    r = sub.add_parser("report"); r.add_argument("--date")
    args = ap.parse_args(argv)
    root = Path(args.root)
    try:
        if args.cmd == "cut":
            tag = f"{args.plugin}-v{args.version}"
            on = _today(args.date).isoformat()
            _write(root / CHANGELOG, cut(_read(root / CHANGELOG), tag, on))
            print(f"cut [Unreleased] -> [{tag}] — {on}")
        elif args.cmd == "check":
            tag = f"{args.plugin}-v{args.version}"
            text = _read(root / CHANGELOG)
            if args.cuttable and not has_release(text, tag):
                if not cuttable(text):
                    raise ChangelogError("[Unreleased] is empty and there is no heading for "
                                         f"[{tag}]: write this release's changelog entry first")
                print(f"ok: [Unreleased] can be cut into [{tag}]")
            elif not has_release(text, tag):
                raise ChangelogError(f"CHANGELOG has no `## [{tag}]` heading: run "
                                     f"`scripts/changelog.py cut {args.plugin} {args.version}` on the release branch")
            else:
                print(f"ok: CHANGELOG has [{tag}]")
        elif args.cmd == "archive":
            on = _today(args.date).isoformat()
            new, moved, n = archive_changelog(_read(root / CHANGELOG), args.keep, on)
            dest = _archive_path(root, on, "CHANGELOG.md")
            if not n:
                print(f"nothing to archive (at most {args.keep} versions)"); return 0
            if args.apply:
                existing = _read(dest) if dest.is_file() else None
                _write(dest, _merge_archive(existing, "# Changelog archive",
                                            "Releases moved out of CHANGELOG.md, newest first.", moved))
                _write(root / CHANGELOG, new)
            print(f"{'moved' if args.apply else 'would move'} {n} version(s) to {dest.relative_to(root).as_posix()}")
        elif args.cmd == "archive-lessons":
            today = _today(args.date)
            new, moved, n = archive_lessons(_read(root / LESSONS), today, args.days, args.keep)
            dest = _archive_path(root, today.isoformat(), "LESSONS_LEARNED.md")
            if not n:
                print(f"nothing to archive (no entry older than {args.days} days beyond the newest {args.keep})"); return 0
            if args.apply:
                existing = _read(dest) if dest.is_file() else None
                _write(dest, _merge_archive(existing, "# Lessons learned archive",
                                            "Entries moved out of docs/LESSONS_LEARNED.md, newest first.", moved))
                _write(root / LESSONS, new)
            print(f"{'moved' if args.apply else 'would move'} {n} entr{'y' if n == 1 else 'ies'} to {dest.relative_to(root).as_posix()}")
        else:
            print("\n".join(report(root, _today(args.date))))
    except ChangelogError as e:
        print(f"changelog: {e}", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"changelog: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
