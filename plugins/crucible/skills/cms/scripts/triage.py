#!/usr/bin/env python3
"""Print the repo's documents as a routing table — title, status, summary — never bodies.

Finding the right document by opening candidates costs the full text of everything you
opened and were wrong about, so a lookup scales with the size of the corpus rather than
with the size of the answer. Ten documents is fine. Fifty is most of a context window
spent to find one page.

This prints what a router needs and nothing else: the path, the status, and the
`ai_summary` if the document declares one. Read this first, pick one document, open that
one. The summary says what a document *is* and when to open it — deliberately not what is
in it, which is what the document is for.

Documents without a summary are listed too, marked, and sorted last: an index that
silently omits them would route you confidently around the half of the corpus it cannot
see, which is worse than having no index.

Exit codes:
    0 — a table was produced
    2 — could not determine: no docs directory, or nothing with frontmatter in it.
        NOT a pass; "I found nothing" and "there is nothing to find" are different claims.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from common import AI_SUMMARY_MAX_BYTES, parse_frontmatter


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


def collect(root: Path) -> list[dict]:
    """Every markdown document under `root`, with whatever frontmatter it declares."""
    out: list[dict] = []
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            fm, _ = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if not fm:
            continue
        summary = (fm.get("ai_summary") or "").strip()
        out.append({
            "path": path.relative_to(root).as_posix(),
            "title": fm.get("title", path.stem),
            "status": fm.get("status", ""),
            "summary": summary,
            "summary_bytes": len(summary.encode("utf-8")),
        })
    # Summarised documents first: they are the ones this table can actually route on.
    return sorted(out, key=lambda d: (not d["summary"], d["path"]))


def render(docs: list[dict]) -> str:
    lines: list[str] = []
    summarised = [d for d in docs if d["summary"]]
    bare = [d for d in docs if not d["summary"]]

    for d in summarised:
        status = f" [{d['status']}]" if d["status"] else ""
        lines.append(f"{d['path']}{status} — {d['title']}")
        lines.append(f"    {d['summary']}")
        if d["summary_bytes"] > AI_SUMMARY_MAX_BYTES:
            lines.append(f"    (!) summary is {d['summary_bytes']} bytes, over the "
                         f"{AI_SUMMARY_MAX_BYTES}-byte budget")
        lines.append("")

    if bare:
        lines.append(f"NO ai_summary ({len(bare)}) — this table cannot route on these:")
        lines.extend(f"  {d['path']} — {d['title']}" for d in bare)
        lines.append("")

    lines.append(f"{len(summarised)} summarised · {len(bare)} without · {len(docs)} total")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="repository path (default: cwd)")
    ap.add_argument("--docs-dir", default="docs",
                    help="directory to triage, relative to --repo (default: docs)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)

    root = Path(a.repo) / a.docs_dir
    if not root.is_dir():
        print(f"cannot determine: {root} is not a directory", file=sys.stderr)
        return 2

    docs = collect(root)
    if not docs:
        print(f"cannot determine: no markdown with frontmatter under {root}", file=sys.stderr)
        return 2

    print(json.dumps(docs, indent=2) if a.json else render(docs))
    return 0


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
