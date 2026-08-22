#!/usr/bin/env python3
"""One-shot script: add CMS frontmatter to all docs/*.md files that lack it.

Infers: title (H1 or filename), status (heuristic), created (first commit date),
last_reviewed_on (today), review_in (by status/path), applies_to (repo).
"""
from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import doc_age

# Repo root to scan. Pass as the first non-flag CLI arg; defaults to cwd.
_pos = [a for a in sys.argv[1:] if not a.startswith("-")]
REPO_ROOT = Path(_pos[0]).expanduser().resolve() if _pos else Path.cwd()

# Files whose status should be 'completed', matched on vendor-neutral name SUFFIXES.
#
# Suffixes only — never a specific document name. A generic plugin that hardcodes one
# repo's filenames is a seam violation (ADR-001): it silently does nothing for every
# other repo, and it goes stale the moment that repo renames or archives the file.
# Earlier revisions listed real per-repo documents here; they were removed, and
# tests/test_seam.py::test_generic_plugin_hardcodes_no_specific_doc_names now fails the
# build if any come back. Every suffix below reads as a document *kind*, not a title.
COMPLETED_PATTERNS = re.compile(
    r"(_REVIEW|_TEST_RUN|_RESULTS|_BASELINE|_COMPLETE|_ASSESSMENT)\.md$",
    re.IGNORECASE,
)

# Lore files — longer review cycle
LORE_PATTERN = re.compile(r"/docs/lore/", re.IGNORECASE)

TODAY = date.today().isoformat()


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


def infer_repo(path: Path) -> str:
    rel = path.relative_to(REPO_ROOT)
    return rel.parts[0] if len(rel.parts) > 1 else "ecosystem"


def infer_title(path: Path, content: str) -> str:
    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return path.stem.replace("_", " ").title()


def infer_status(path: Path) -> str:
    if COMPLETED_PATTERNS.search(path.name):
        return "completed"
    return "active"


def infer_review_in(path: Path, status: str) -> str:
    if status == "completed":
        return "24 months"
    if LORE_PATTERN.search(str(path)):
        return "12 months"
    return "6 months"


def infer_created(path: Path) -> str:
    """The date this document entered the repository, from history rather than mtime.

    This is the worst of the four sites the mtime bug touched, because it is the only one
    that *writes*. A missed archive finding is recomputed correctly the next time the
    linter runs; a wrong `created:` is persisted into the file, and from there it feeds
    `review_in` staleness forever — the document reports itself as freshly created for
    the rest of its life, on every machine, long after the clone that caused it.

    Falls back to today, never to mtime: an honest "I do not know, so: now" is strictly
    better than a confident wrong date, because the wrong date is indistinguishable from
    a real one once it is in the file.
    """
    first, _source = doc_age.first_committed(path)
    if first is not None:
        return first.isoformat()
    return TODAY


def make_frontmatter(path: Path, content: str) -> str:
    title = infer_title(path, content)
    status = infer_status(path)
    created = infer_created(path)
    review_in = infer_review_in(path, status)
    repo = infer_repo(path)

    fm = (
        f"---\n"
        f"title: {title}\n"
        f"status: {status}\n"
        f"created: {created}\n"
        f"last_reviewed_on: {TODAY}\n"
        f"review_in: {review_in}\n"
        f"applies_to: {repo}\n"
        f"---\n\n"
    )
    return fm


def process(path: Path, dry_run: bool = False) -> str:
    content = path.read_text(encoding="utf-8", errors="replace")
    if content.startswith("---\n"):
        return "skip (already has frontmatter)"
    fm = make_frontmatter(path, content)
    if not dry_run:
        path.write_text(fm + content, encoding="utf-8")
    return f"{'[DRY] ' if dry_run else ''}added ({infer_status(path)})"


def main():
    dry_run = "--dry-run" in sys.argv
    paths = sorted(REPO_ROOT.rglob("*.md"))

    added = skipped = 0
    for p in paths:
        # Only files under a docs/ directory, excluding archive/
        parts = p.relative_to(REPO_ROOT).parts
        if "docs" not in parts:
            continue
        if "archive" in parts:
            continue
        if any(d.startswith(".") or d in {"node_modules", ".venv", "venv"} for d in parts):
            continue

        result = process(p, dry_run=dry_run)
        rel = p.relative_to(REPO_ROOT)
        print(f"  {result:45s} {rel}")
        if "skip" in result:
            skipped += 1
        else:
            added += 1

    print(f"\nSummary: {added} added, {skipped} skipped")


if __name__ == "__main__":
    _utf8_stdio()
    main()
