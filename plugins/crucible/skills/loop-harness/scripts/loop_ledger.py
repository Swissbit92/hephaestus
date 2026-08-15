"""LOOP-STATE.md ledger management for loop-harness — pure stdlib.

The ledger is the loop's durable memory (note-taking against context rot): a small markdown
file with fixed sections. This module does the *structural* mechanics — render, append a bullet
under a section, and structurally compact the Timeline (keep the most recent N, archive the
rest). *Semantic* compaction (summarizing what happened) is the agent's job, described in
SKILL.md — deterministic code shouldn't pretend to summarize.

CLI:
    python3 loop_ledger.py init --goal "..." --run-id loop-... [--out LOOP-STATE.md]
    python3 loop_ledger.py append --file LOOP-STATE.md --section timeline --entry "..."
    python3 loop_ledger.py compact --file LOOP-STATE.md [--keep 10]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

PLACEHOLDER = "_(none yet)_"
ARCHIVE_PREFIX = "_(archived "

HEADINGS = ["Open hypotheses", "Decisions", "Timeline", "Needs-me"]
ALIASES = {
    "hypothesis": "Open hypotheses", "hypotheses": "Open hypotheses",
    "open hypotheses": "Open hypotheses",
    "decision": "Decisions", "decisions": "Decisions",
    "timeline": "Timeline", "finding": "Timeline", "action": "Timeline", "event": "Timeline",
    "needs-me": "Needs-me", "needs_me": "Needs-me", "needsme": "Needs-me", "needs me": "Needs-me",
}


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_section(name: str) -> str:
    key = name.strip().lower()
    if key in ALIASES:
        return ALIASES[key]
    raise ValueError(f"unknown section {name!r}; valid: {sorted(set(ALIASES))}")


def init_ledger(goal: str, run_id: str, *, status: str = "armed", updated: str | None = None) -> str:
    updated = updated or _now_iso()
    body = [f"# LOOP-STATE: {run_id}", "",
            f"- **Goal:** {goal}",
            f"- **Status:** {status}",
            f"- **Updated:** {updated}", ""]
    for h in HEADINGS:
        body += [f"## {h}", PLACEHOLDER, ""]
    return "\n".join(body).rstrip() + "\n"


def _section_bounds(lines: list[str], canonical: str) -> tuple[int, int] | tuple[None, None]:
    """Return (heading_index, section_end_exclusive) for a `## {canonical}` heading."""
    head = f"## {canonical}"
    for i, line in enumerate(lines):
        if line.strip() == head:
            end = len(lines)
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("## "):
                    end = j
                    break
            return i, end
    return None, None


def _body_entries(lines: list[str], start: int, end: int) -> list[str]:
    """Real bullet entries in a section (placeholder + blanks stripped)."""
    out = []
    for line in lines[start:end]:
        s = line.strip()
        if not s or s == PLACEHOLDER:
            continue
        out.append(line.rstrip())
    return out


def parse_sections(text: str) -> dict[str, list[str]]:
    lines = text.splitlines()
    result: dict[str, list[str]] = {}
    for h in HEADINGS:
        idx, end = _section_bounds(lines, h)
        result[h] = [] if idx is None else _body_entries(lines, idx + 1, end)
    return result


def _format_bullet(canonical: str, entry: str, when: str) -> str:
    entry = entry.strip()
    if canonical == "Open hypotheses":
        return f"- [ ] {entry}"
    if canonical in ("Decisions", "Timeline"):
        return f"- {when} — {entry}"
    return f"- {entry}"  # Needs-me


def _set_updated(lines: list[str], when: str) -> None:
    for i, line in enumerate(lines):
        if line.startswith("- **Updated:**"):
            lines[i] = f"- **Updated:** {when}"
            return


def set_status(text: str, status: str, *, updated: str | None = None) -> str:
    """Update the ledger's header `Status` field (and optionally `Updated`). Used at disarm so the
    ledger reflects the final run state instead of staying 'armed'."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("- **Status:**"):
            lines[i] = f"- **Status:** {status}"
            break
    if updated is not None:
        _set_updated(lines, updated)
    return "\n".join(lines).rstrip() + "\n"


def append_entry(text: str, section: str, entry: str, *, when: str | None = None) -> str:
    canonical = resolve_section(section)
    when = when or _now_iso()
    lines = text.splitlines()
    idx, end = _section_bounds(lines, canonical)
    if idx is None:
        raise ValueError(f"ledger is missing the '## {canonical}' section")
    body = _body_entries(lines, idx + 1, end)
    body.append(_format_bullet(canonical, entry, when))
    rebuilt = lines[: idx + 1] + body + [""] + lines[end:]
    _set_updated(rebuilt, when)
    return "\n".join(rebuilt).rstrip() + "\n"


def compact(text: str, *, keep_recent: int = 10) -> str:
    """Structurally compact the Timeline: keep the most recent `keep_recent` entries, replace
    the older ones with a single archive marker. Other sections are left untouched."""
    if keep_recent < 0:
        raise ValueError("keep_recent must be >= 0")
    lines = text.splitlines()
    idx, end = _section_bounds(lines, "Timeline")
    if idx is None:
        return text
    entries = _body_entries(lines, idx + 1, end)
    # drop any prior archive marker so repeated compaction doesn't stack them — anchored to the
    # start of the bullet so a real entry merely mentioning the phrase isn't dropped
    entries = [e for e in entries if not e.lstrip().startswith(f"- {ARCHIVE_PREFIX}")]
    if len(entries) <= keep_recent:
        return text
    archived = len(entries) - keep_recent
    kept = entries[-keep_recent:] if keep_recent else []
    marker = f"- {ARCHIVE_PREFIX}{archived} earlier entries)_"
    new_body = [marker] + kept
    rebuilt = lines[: idx + 1] + new_body + [""] + lines[end:]
    return "\n".join(rebuilt).rstrip() + "\n"


# --- CLI ---

def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


def _write(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _cmd_init(args) -> int:
    text = init_ledger(args.goal, args.run_id, status=args.status)
    _write(args.out, text)
    print(f"[loop-ledger] wrote {args.out}")
    return 0


def _cmd_append(args) -> int:
    _write(args.file, append_entry(_read(args.file), args.section, args.entry))
    print(f"[loop-ledger] appended to {args.section} in {args.file}")
    return 0


def _cmd_compact(args) -> int:
    _write(args.file, compact(_read(args.file), keep_recent=args.keep))
    print(f"[loop-ledger] compacted {args.file} (kept {args.keep})")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="loop_ledger", description="LOOP-STATE.md ledger management")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="create a fresh LOOP-STATE.md")
    p_init.add_argument("--goal", required=True)
    p_init.add_argument("--run-id", required=True, dest="run_id")
    p_init.add_argument("--status", default="armed")
    p_init.add_argument("--out", default="LOOP-STATE.md")
    p_init.set_defaults(func=_cmd_init)

    p_app = sub.add_parser("append", help="append a bullet under a section")
    p_app.add_argument("--file", required=True)
    p_app.add_argument("--section", required=True)
    p_app.add_argument("--entry", required=True)
    p_app.set_defaults(func=_cmd_append)

    p_comp = sub.add_parser("compact", help="structurally compact the Timeline")
    p_comp.add_argument("--file", required=True)
    p_comp.add_argument("--keep", type=int, default=10)
    p_comp.set_defaults(func=_cmd_compact)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
