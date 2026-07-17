#!/usr/bin/env python3
"""CMS migration helper — propose-and-approve.

Reports proposed structural changes for an existing repo. NEVER paraphrases prose.
Two kinds of proposals:

  1. Archive moves — files matching ARCHIVE_PATTERNS + >60 days old + not allowlisted.
     Mode: auto-apply with --apply (moves file into docs/archive/YYYY-MM/, adds
     `status: completed` frontmatter if missing). Non-destructive: git preserves history.

  2. CLAUDE.md extraction suggestions — heuristic scan for long inline sections that
     are candidates for extraction to docs/shared/ + @path import. Reported only
     (never auto-applied) because CLAUDE.md content is nuance-critical.

Usage:
    migrate.py <repo-path>              # dry-run, report only
    migrate.py <repo-path> --apply      # auto-apply archive moves (still reports CLAUDE.md proposals)
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import date
from pathlib import Path

from common import (
    ARCHIVE_ALLOWLIST,
    ARCHIVE_PATTERNS,
    iter_md_files,
    parse_frontmatter,
)

ARCHIVE_AGE_DAYS = 60
EXTRACTION_HEADING_THRESHOLD_LINES = 25  # sections >25 lines under a single H2 are extraction candidates


def find_archive_candidates(repo: Path) -> list[Path]:
    candidates: list[Path] = []
    for md in iter_md_files(repo, include_archive=False):
        if md.name in ARCHIVE_ALLOWLIST:
            continue
        if not any(p.match(md.name) for p in ARCHIVE_PATTERNS):
            continue
        try:
            mtime = date.fromtimestamp(md.stat().st_mtime)
        except Exception:
            continue
        if (date.today() - mtime).days <= ARCHIVE_AGE_DAYS:
            continue
        candidates.append(md)
    return candidates


def archive_destination(repo: Path, src: Path) -> Path:
    try:
        mtime = date.fromtimestamp(src.stat().st_mtime)
    except Exception:
        mtime = date.today()
    dest_dir = repo / "docs" / "archive" / mtime.strftime("%Y-%m")
    return dest_dir / src.name


def ensure_completed_frontmatter(text: str) -> str:
    fm, body_start = parse_frontmatter(text)
    if not fm:
        # Prepend minimal frontmatter
        today = date.today().isoformat()
        fm_block = (
            "---\n"
            f"status: completed\n"
            f"last_reviewed_on: {today}\n"
            "---\n\n"
        )
        return fm_block + text
    # Replace status line in existing frontmatter
    lines = text.splitlines(keepends=True)
    out_lines = list(lines)
    found_status = False
    # Frontmatter is between the two '---' fences
    for i in range(1, len(out_lines)):
        if out_lines[i].strip() == "---":
            break
        if out_lines[i].lstrip().startswith("status:"):
            out_lines[i] = "status: completed\n"
            found_status = True
    if not found_status:
        # Insert status line after opening fence
        out_lines.insert(1, "status: completed\n")
    return "".join(out_lines)


H2_RE = re.compile(r"^##\s+(.+)$")


def find_extraction_candidates(claude_md: Path) -> list[tuple[str, int, int]]:
    """Return [(section_title, start_line, end_line)] for H2 sections >threshold lines."""
    if not claude_md.exists():
        return []
    lines = claude_md.read_text(encoding="utf-8", errors="replace").splitlines()
    sections: list[tuple[str, int, int]] = []
    current: tuple[str, int] | None = None  # (title, start)
    for i, line in enumerate(lines):
        m = H2_RE.match(line)
        if m:
            if current is not None:
                start_title, start = current
                length = i - start
                if length > EXTRACTION_HEADING_THRESHOLD_LINES:
                    sections.append((start_title, start, i))
            current = (m.group(1).strip(), i)
    if current is not None:
        start_title, start = current
        length = len(lines) - start
        if length > EXTRACTION_HEADING_THRESHOLD_LINES:
            sections.append((start_title, start, len(lines)))
    return sections


def main() -> int:
    ap = argparse.ArgumentParser(description="Propose (and optionally apply) CMS migrations")
    ap.add_argument("path", help="repo path")
    ap.add_argument("--apply", action="store_true", help="auto-apply archive moves (CLAUDE.md proposals are ALWAYS report-only)")
    args = ap.parse_args()

    repo = Path(args.path).resolve()
    if not repo.is_dir():
        print(f"error: not a directory: {repo}", file=sys.stderr)
        return 2

    print(f"CMS migrate: {repo}")
    print(f"Mode: {'APPLY (archive moves)' if args.apply else 'DRY RUN'}")
    print()

    # 1. Archive candidates
    archive_cands = find_archive_candidates(repo)
    print(f"=== Archive candidates ({len(archive_cands)}) ===")
    applied = 0
    for src in archive_cands:
        dst = archive_destination(repo, src)
        rel_src = src.relative_to(repo)
        rel_dst = dst.relative_to(repo)
        print(f"  {rel_src}  →  {rel_dst}")
        if args.apply:
            dst.parent.mkdir(parents=True, exist_ok=True)
            text = src.read_text(encoding="utf-8", errors="replace")
            text = ensure_completed_frontmatter(text)
            dst.write_text(text, encoding="utf-8")
            src.unlink()
            applied += 1
    if args.apply:
        print(f"  Applied {applied} archive moves.")
    print()

    # 2. CLAUDE.md extraction proposals (report-only)
    claude_md = repo / "CLAUDE.md"
    extractions = find_extraction_candidates(claude_md)
    print(f"=== CLAUDE.md extraction proposals ({len(extractions)}) ===")
    print("(Report-only. Human must approve content moves. ETH Zurich: auto-paraphrase degrades quality.)")
    if not claude_md.exists():
        print("  (no CLAUDE.md)")
    elif not extractions:
        print("  (no sections exceed threshold)")
    else:
        for title, start, end in extractions:
            lines = end - start
            print(f"  {claude_md.relative_to(repo)}:{start + 1}-{end}  ({lines} lines)  ## {title}")
            print(f"    → candidate target: docs/shared/{_slug(title)}.md  (replace with `@docs/shared/{_slug(title)}.md`)")
    print()

    total_lines = len(claude_md.read_text(encoding="utf-8", errors="replace").splitlines()) if claude_md.exists() else 0
    print(f"Summary: {len(archive_cands)} archive candidates, {len(extractions)} extraction proposals, CLAUDE.md={total_lines} lines")
    return 0


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


if __name__ == "__main__":
    sys.exit(main())
