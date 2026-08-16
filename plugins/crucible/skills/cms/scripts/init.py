#!/usr/bin/env python3
"""CMS scaffolder. Idempotent: skips files that already exist.

Usage:
    init.py <repo-path> [--repo-name NAME] [--purpose "one-liner"] [--ecosystem-root PATH]

Creates:
    README.md, CLAUDE.md, CHANGELOG.md, SECURITY.md,
    docs/ARCHITECTURE.md, docs/ROADMAP.md, docs/LESSONS_LEARNED.md, docs/THREAT_LEVEL.md,
    docs/decisions/, docs/archive/
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import TEMPLATES_DIR, today_iso


TEMPLATE_MAP = [
    ("README.md", "README.md"),
    ("CLAUDE.md", "CLAUDE.md"),
    ("CHANGELOG.md", "CHANGELOG.md"),
    ("SECURITY.md", "SECURITY.md"),
    ("docs/ARCHITECTURE.md", "ARCHITECTURE.md"),
    ("docs/ROADMAP.md", "ROADMAP.md"),
    ("docs/LESSONS_LEARNED.md", "LESSONS_LEARNED.md"),
    ("docs/THREAT_LEVEL.md", "THREAT_LEVEL.md"),
    # Scaffolded, but deliberately NOT added to REQUIRED_FILES: a repo with no standing
    # constraints is not a repo doing something wrong, so its absence must never error.
    ("docs/INVARIANTS.md", "INVARIANTS.md"),
]


def _utf8_stdio() -> None:
    """Force UTF-8 on the streams this script writes to.

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


def substitute(text: str, *, repo_name: str, purpose: str) -> str:
    return (text
            .replace("{{REPO_NAME}}", repo_name)
            .replace("{{ONE_LINE_PURPOSE}}", purpose)
            .replace("{{TODAY}}", today_iso())
            .replace("{{INVARIANT_1}}", "TBD — critical invariant 1")
            .replace("{{INVARIANT_2}}", "TBD — critical invariant 2")
            .replace("{{INVARIANT_3}}", "TBD — critical invariant 3"))


def scaffold(repo: Path, *, repo_name: str, purpose: str) -> list[tuple[str, str]]:
    """Returns list of (action, relpath) tuples: action is 'created' | 'skipped'."""
    actions: list[tuple[str, str]] = []
    # Directories
    for d in ["docs", "docs/decisions", "docs/archive"]:
        dp = repo / d
        if dp.is_dir():
            actions.append(("skipped-dir", d))
        else:
            dp.mkdir(parents=True, exist_ok=True)
            actions.append(("created-dir", d))
    # .gitkeep so archive/decisions show up in git
    for d in ["docs/decisions", "docs/archive"]:
        keep = repo / d / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
    # Files
    for rel, template_name in TEMPLATE_MAP:
        dst = repo / rel
        if dst.exists():
            actions.append(("skipped", rel))
            continue
        src = TEMPLATES_DIR / template_name
        body = substitute(src.read_text(encoding="utf-8"), repo_name=repo_name, purpose=purpose)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(body, encoding="utf-8")
        actions.append(("created", rel))
    return actions


def main() -> int:
    ap = argparse.ArgumentParser(description="Scaffold CMS doc skeleton into a repo")
    ap.add_argument("path", help="repo path")
    ap.add_argument("--repo-name", help="override repo name (default: dir basename)")
    ap.add_argument("--purpose", default="TBD — one-line purpose", help="one-line repo purpose")
    args = ap.parse_args()

    repo = Path(args.path).resolve()
    if not repo.is_dir():
        print(f"error: not a directory: {repo}", file=sys.stderr)
        return 2
    name = args.repo_name or repo.name
    print(f"CMS init: {name} ({repo})")
    actions = scaffold(repo, repo_name=name, purpose=args.purpose)
    created = [a for a in actions if a[0].startswith("created")]
    skipped = [a for a in actions if a[0].startswith("skipped")]
    for act, rel in actions:
        print(f"  {act:14s} {rel}")
    print()
    print(f"Summary: {len(created)} created, {len(skipped)} skipped (already present)")
    print("Next steps:")
    print(f"  1. Fill in TBD placeholders in README.md, CLAUDE.md, SECURITY.md, docs/ARCHITECTURE.md, docs/THREAT_LEVEL.md")
    scripts = Path(__file__).resolve().parent
    print(f"  2. Run: python3 {scripts}/check.py {repo}")
    print(f"  3. Add your first ADR: python3 {scripts}/new_adr.py \"<title>\" --path {repo}/docs/decisions")
    return 0


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main())
