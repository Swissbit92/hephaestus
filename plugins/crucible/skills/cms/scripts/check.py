#!/usr/bin/env python3
"""CMS linter — tiered Error / Warning output.

Usage:
    check.py [<path>]                    # full repo audit
    check.py --mechanical <file>         # fast frontmatter + @path check (hook mode)
    check.py --file <file>               # deep single-file check

Exit codes:
    0 — no errors
    1 — one or more Error-level findings
    2 — usage error
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from common import (
    ARCHIVE_ALLOWLIST,
    ARCHIVE_PATTERNS,
    FRONTMATTER_EXEMPT,
    FRONTMATTER_REQUIRED,
    FRONTMATTER_STATUSES,
    FRONTMATTER_THREAT_LEVELS,
    REQUIRED_DIRS,
    REQUIRED_FILES,
    Finding,
    find_atpath_imports,
    iter_md_files,
    load_state,
    parse_frontmatter,
    parse_iso_date,
    parse_review_in,
    repo_name,
    save_state,
)


def check_frontmatter(path: Path, required: bool) -> list[Finding]:
    text = path.read_text(errors="replace")
    fm, _ = parse_frontmatter(text)
    findings: list[Finding] = []
    rel = str(path)
    if not fm:
        if required:
            findings.append(Finding("error", rel, "missing frontmatter (required for files under docs/)"))
        return findings
    # Required-field completeness only applies where frontmatter is required. But any
    # frontmatter that IS present is validated for controlled-vocab + field validity even
    # on exempt files — a bad status/date on README should still be caught.
    if required:
        missing = FRONTMATTER_REQUIRED - set(fm)
        if missing:
            findings.append(Finding("error", rel, f"frontmatter missing fields: {sorted(missing)}"))
    status = fm.get("status")
    if status and status not in FRONTMATTER_STATUSES:
        findings.append(Finding("error", rel, f"invalid status '{status}'; expected one of {sorted(FRONTMATTER_STATUSES)}"))
    # threat_level controlled vocabulary (only validated when present)
    threat_level = fm.get("threat_level")
    if threat_level and threat_level not in FRONTMATTER_THREAT_LEVELS:
        findings.append(Finding("error", rel, f"invalid threat_level '{threat_level}'; expected one of {sorted(FRONTMATTER_THREAT_LEVELS)}"))
    # Date validity
    for fld in ("created", "last_reviewed_on"):
        if fld in fm and parse_iso_date(fm[fld]) is None:
            findings.append(Finding("error", rel, f"frontmatter field '{fld}' is not YYYY-MM-DD: {fm[fld]!r}"))
    if "review_in" in fm and parse_review_in(fm["review_in"]) is None:
        findings.append(Finding("error", rel, f"frontmatter 'review_in' unparseable: {fm['review_in']!r}"))
    # review_by expiry
    reviewed = parse_iso_date(fm.get("last_reviewed_on", ""))
    review_days = parse_review_in(fm.get("review_in", ""))
    if reviewed and review_days is not None:
        review_by = reviewed + timedelta(days=review_days)
        if review_by < date.today() and fm.get("status") == "active":
            findings.append(Finding("warning", rel, f"past review_by {review_by} (last_reviewed_on={reviewed}, review_in={fm['review_in']})"))
    return findings


def check_atpath_imports(path: Path) -> list[Finding]:
    text = path.read_text(errors="replace")
    findings: list[Finding] = []
    for raw, target in find_atpath_imports(text, path.parent):
        if not target.exists():
            findings.append(Finding("error", str(path), f"@{raw} points to missing file: {target}"))
    return findings


def check_archive_candidate(path: Path) -> list[Finding]:
    name = path.name
    if name in ARCHIVE_ALLOWLIST:
        return []
    if "/archive/" in str(path).replace("\\", "/"):
        return []  # already archived
    matches_pattern = any(p.match(name) for p in ARCHIVE_PATTERNS)
    if not matches_pattern:
        return []
    # Check age
    try:
        mtime = date.fromtimestamp(path.stat().st_mtime)
    except Exception:
        return []
    age_days = (date.today() - mtime).days
    if age_days > 60:
        return [Finding("warning", str(path),
                        f"archive-candidate filename + mtime {mtime} ({age_days} days old); consider moving to docs/archive/YYYY-MM/")]
    return []


def check_required_files(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    for rel in REQUIRED_FILES:
        if not (repo / rel).exists():
            findings.append(Finding("error", str(repo / rel), f"required file missing ({rel})"))
    for rel in REQUIRED_DIRS:
        if not (repo / rel).is_dir():
            findings.append(Finding("warning", str(repo / rel), f"required dir missing ({rel}); `/cms init` would create it"))
    return findings


def check_claude_md_size_trend(repo: Path) -> list[Finding]:
    claude = repo / "CLAUDE.md"
    if not claude.exists():
        return []
    lines = len(claude.read_text(errors="replace").splitlines())
    state = load_state("size_history")
    key = str(repo.resolve())
    entry = state.get(key, {})
    prev = entry.get("claude_md_lines")
    findings: list[Finding] = []
    findings.append(Finding("info", str(claude), f"CLAUDE.md size: {lines} lines (previous: {prev if prev is not None else 'n/a'})"))
    if prev is not None and lines > prev * 1.2 and lines > 100:
        findings.append(Finding("warning", str(claude),
                                f"CLAUDE.md grew >20% ({prev} → {lines} lines); consider extracting to docs/shared/"))
    # Persist
    entry["claude_md_lines"] = lines
    entry["last_checked"] = date.today().isoformat()
    state[key] = entry
    save_state("size_history", state)
    return findings


def check_architecture_page(repo: Path) -> list[Finding]:
    """Warn when a rendered ARCHITECTURE.html no longer matches its source.

    Warning, not error: this is advisory precisely so it stays trustworthy. A
    gate that blocks on a regenerable artifact is a gate people learn to bypass,
    and then it protects nothing. Silent when there is no rendered page — most
    repos have prose long before they have a rendered view, and flagging them
    would make the check cry wolf across the estate.
    """
    md = repo / "docs" / "ARCHITECTURE.md"
    page = repo / "docs" / "ARCHITECTURE.html"
    if not md.exists() or not page.exists():
        return []
    try:
        import render
    except Exception:                                    # noqa: BLE001
        return []
    if render.is_current(md, page):
        return []
    return [Finding("warning", str(page),
                    "generated page is out of date with ARCHITECTURE.md "
                    "— re-render with `/cms render`")]


def run_repo_check(repo: Path) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(check_required_files(repo))
    findings.extend(check_claude_md_size_trend(repo))
    findings.extend(check_architecture_page(repo))
    # Per-file checks
    for md in iter_md_files(repo, include_archive=False):
        required_fm = "/docs/" in str(md).replace("\\", "/") and md.name not in FRONTMATTER_EXEMPT
        findings.extend(check_frontmatter(md, required=required_fm))
        findings.extend(check_atpath_imports(md))
        findings.extend(check_archive_candidate(md))
    return findings


def run_mechanical_check(file: Path) -> list[Finding]:
    """Fast, hook-safe: frontmatter presence (if under docs/) + @path validity only."""
    findings: list[Finding] = []
    if not file.exists():
        return []  # new file; other rules caught at save time
    required_fm = "/docs/" in str(file).replace("\\", "/") and file.name not in FRONTMATTER_EXEMPT
    findings.extend(check_frontmatter(file, required=required_fm))
    findings.extend(check_atpath_imports(file))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="CMS linter")
    ap.add_argument("path", nargs="?", default=".", help="repo path (default: .)")
    ap.add_argument("--mechanical", metavar="FILE", help="fast check on one file (hook mode)")
    ap.add_argument("--file", metavar="FILE", help="deep check on one file")
    args = ap.parse_args()

    if args.mechanical:
        findings = run_mechanical_check(Path(args.mechanical))
    elif args.file:
        f = Path(args.file)
        required_fm = "/docs/" in str(f).replace("\\", "/") and f.name not in FRONTMATTER_EXEMPT
        findings = check_frontmatter(f, required=required_fm) + check_atpath_imports(f) + check_archive_candidate(f)
    else:
        repo = Path(args.path).resolve()
        if not repo.is_dir():
            print(f"error: not a directory: {repo}", file=sys.stderr)
            return 2
        print(f"CMS check: {repo_name(repo)} ({repo})")
        findings = run_repo_check(repo)

    errors = [f for f in findings if f.level == "error"]
    warnings = [f for f in findings if f.level == "warning"]
    infos = [f for f in findings if f.level == "info"]

    for f in errors + warnings + infos:
        print(f.format())

    print()
    print(f"Summary: {len(errors)} error(s), {len(warnings)} warning(s), {len(infos)} info(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
