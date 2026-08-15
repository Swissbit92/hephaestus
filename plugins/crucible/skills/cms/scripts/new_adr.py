#!/usr/bin/env python3
"""Scaffold the next numbered ADR with the Nygard 5-field template.

Usage:
    new_adr.py "<title>" [--path <dir>] [--repo-name NAME]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from common import TEMPLATES_DIR, today_iso


SLUG_RE = re.compile(r"[^a-z0-9]+")
NUM_RE = re.compile(r"^(\d{3})-")


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


def slugify(title: str) -> str:
    s = SLUG_RE.sub("-", title.lower()).strip("-")
    return s or "adr"


def next_number(adr_dir: Path) -> int:
    existing = [NUM_RE.match(p.name) for p in adr_dir.glob("*.md")]
    nums = [int(m.group(1)) for m in existing if m]
    return (max(nums) + 1) if nums else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Create the next ADR from template")
    ap.add_argument("title", help="ADR title (e.g. \"Postgres as the primary datastore\")")
    ap.add_argument("--path", default="docs/decisions", help="ADR directory (default: docs/decisions)")
    ap.add_argument("--repo-name", default=None, help="applies_to field (default: parent repo dir name)")
    args = ap.parse_args()

    adr_dir = Path(args.path).resolve()
    adr_dir.mkdir(parents=True, exist_ok=True)
    n = next_number(adr_dir)
    filename = f"{n:03d}-{slugify(args.title)}.md"
    dst = adr_dir / filename
    if dst.exists():
        print(f"error: {dst} already exists", file=sys.stderr)
        return 2

    repo_name = args.repo_name or _infer_repo_name(adr_dir)
    body = (TEMPLATES_DIR / "ADR.md").read_text(encoding="utf-8")
    body = (body
            .replace("{{TITLE}}", args.title)
            .replace("{{NUMBER}}", f"{n:03d}")
            .replace("{{TODAY}}", today_iso())
            .replace("{{REPO_NAME}}", repo_name))
    dst.write_text(body, encoding="utf-8")
    print(f"Created: {dst}")
    return 0


def _infer_repo_name(adr_dir: Path) -> str:
    # Walk up until we find a README.md or hit the filesystem root.
    p = adr_dir
    for _ in range(6):
        if (p / "README.md").exists() or (p / ".git").exists():
            return p.name
        if p.parent == p:
            break
        p = p.parent
    return adr_dir.parent.name


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main())
