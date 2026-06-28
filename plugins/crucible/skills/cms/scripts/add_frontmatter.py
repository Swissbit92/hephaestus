#!/usr/bin/env python3
"""One-shot script: add CMS frontmatter to all docs/*.md files that lack it.

Infers: title (H1 or filename), status (heuristic), created (mtime),
last_reviewed_on (today), review_in (by status/path), applies_to (repo).
"""
from __future__ import annotations

import re
import sys
from datetime import date, datetime
from pathlib import Path

# Repo root to scan. Pass as the first non-flag CLI arg; defaults to cwd.
_pos = [a for a in sys.argv[1:] if not a.startswith("-")]
REPO_ROOT = Path(_pos[0]).expanduser().resolve() if _pos else Path.cwd()

# Files whose status should be 'completed' based on name patterns
COMPLETED_PATTERNS = re.compile(
    r"(_REVIEW|_TEST_RUN|_RESULTS|_BASELINE|_COMPLETE|REMEDIATION_PROGRESS|"
    r"JUPITER_WALLET_IMPLEMENTATION|LORE_DEEPDIVE_PLAN|MULTI_ASSET_PLAN|OAUTH_IMPLEMENTATION_PLAN|"
    r"E2E_TEST_RUN|EDGE_CASE_TEST_RESULTS|QA_WAVE1|UX_WAVE1|UI_TESTING_BASELINE|"
    r"SCORER_PROMPT_IMPROVEMENTS)\.md$",
    re.IGNORECASE,
)

# Lore files — longer review cycle
LORE_PATTERN = re.compile(r"/docs/lore/", re.IGNORECASE)

TODAY = date.today().isoformat()


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
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
    except Exception:
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
    content = path.read_text(errors="replace")
    if content.startswith("---\n"):
        return "skip (already has frontmatter)"
    fm = make_frontmatter(path, content)
    if not dry_run:
        path.write_text(fm + content)
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
    main()
