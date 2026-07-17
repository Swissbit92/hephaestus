#!/usr/bin/env python3
"""CMS drift detector. Regex allowlist of known-drift-prone facts.

Reads fact definitions from the skill's state/sync_facts.yaml (override with --facts).
Scans all *.md under <root> (excluding archive/). Reports:
  - matches whose captured value != expected_value (drift from canonical)
  - facts with multiple distinct captured values across files (internal inconsistency)

Usage:
    sync.py [<root>]            # default: cwd

Note: uses a minimal YAML subset parser to avoid requiring PyYAML.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from common import SKILL_ROOT, iter_md_files


def load_facts(path: Path) -> list[dict]:
    """Minimal YAML parser for the sync_facts.yaml format (list of facts with
    name/pattern/expected_value/note keys). Only supports this exact layout."""
    text = path.read_text(encoding="utf-8")
    facts: list[dict] = []
    current: dict | None = None
    in_note = False
    note_lines: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            if in_note:
                note_lines.append("")
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("facts:"):
            continue
        if stripped.startswith("- name:"):
            if current is not None:
                if in_note:
                    current["note"] = "\n".join(note_lines).strip()
                facts.append(current)
            current = {"name": _strip_quotes(stripped[len("- name:"):].strip())}
            in_note = False
            note_lines = []
            continue
        if current is None:
            continue
        if in_note:
            # Collect until next same-indent key or new entry
            if indent >= 6 and not re.match(r"^[a-z_]+:", stripped):
                note_lines.append(stripped)
                continue
            current["note"] = "\n".join(note_lines).strip()
            in_note = False
            note_lines = []
        if stripped.startswith("pattern:"):
            current["pattern"] = _strip_quotes(stripped[len("pattern:"):].strip())
        elif stripped.startswith("expected_value:"):
            v = stripped[len("expected_value:"):].strip()
            current["expected_value"] = None if v == "null" else _strip_quotes(v)
        elif stripped.startswith("note:"):
            rest = stripped[len("note:"):].strip()
            if rest == "|":
                in_note = True
                note_lines = []
            else:
                current["note"] = _strip_quotes(rest)
    if current is not None:
        if in_note:
            current["note"] = "\n".join(note_lines).strip()
        facts.append(current)
    return facts


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] == s[-1] and s[0] in {'"', "'"}:
        return s[1:-1]
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description="CMS cross-repo drift detector")
    ap.add_argument("root", nargs="?", default=".", help="ecosystem root (default: .)")
    ap.add_argument("--facts", default=str(SKILL_ROOT / "state" / "sync_facts.yaml"), help="facts file")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"error: not a directory: {root}", file=sys.stderr)
        return 2
    facts = load_facts(Path(args.facts))
    if not facts:
        print("warning: no facts loaded; nothing to check", file=sys.stderr)
        return 0

    print(f"CMS sync: scanning {root}")
    print(f"  Facts loaded: {len(facts)}")
    print()

    total_issues = 0
    for fact in facts:
        name = fact["name"]
        pattern = fact.get("pattern")
        if not pattern:
            continue
        expected = fact.get("expected_value")
        try:
            rx = re.compile(pattern)
        except re.error as e:
            print(f"[FACT {name}] bad regex {pattern!r}: {e}", file=sys.stderr)
            continue
        # Group: captured_value -> [files]
        grouped: dict[str, list[str]] = defaultdict(list)
        for md in iter_md_files(root, include_archive=False):
            # Skip decisions/ and ecosystem/docs/shared: those are sources of truth
            relparts = set(md.relative_to(root).parts) if md.is_relative_to(root) else set()
            if "decisions" in relparts:
                continue
            try:
                text = md.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for m in rx.finditer(text):
                # Prefer first non-empty group as the "captured value"; fall back to whole match
                groups = [g for g in m.groups() if g]
                val = groups[0] if groups else m.group(0)
                grouped[val].append(str(md.relative_to(root)))
        if not grouped:
            continue
        issues = []
        if expected is not None:
            for val, files in grouped.items():
                if val != expected:
                    issues.append((val, files))
        else:
            # No canonical value → any occurrence is suspicious (e.g. Jupiter)
            for val, files in grouped.items():
                issues.append((val, files))
        if issues:
            total_issues += 1
            print(f"[DRIFT] {name}  (expected: {expected!r})")
            if fact.get("note"):
                for line in fact["note"].splitlines():
                    if line.strip():
                        print(f"    {line}")
            for val, files in issues:
                uniq = sorted(set(files))
                print(f"    matched {val!r} in {len(uniq)} file(s):")
                for f in uniq[:10]:
                    print(f"      - {f}")
                if len(uniq) > 10:
                    print(f"      ... and {len(uniq) - 10} more")
            print()

    print(f"Summary: {total_issues} fact(s) with drift")
    return 1 if total_issues else 0


if __name__ == "__main__":
    sys.exit(main())
