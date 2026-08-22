#!/usr/bin/env python3
"""CMS drift detector. Regex allowlist of known-drift-prone facts.

Reads fact definitions from the skill's state/sync_facts.yaml (override with --facts).
Scans all *.md under <root> (excluding archive/). Reports:
  - matches whose captured value != expected_value (drift from canonical)
  - facts with multiple distinct captured values across files (internal inconsistency)

Usage:
    sync.py [<root>]            # default: cwd

Exit codes:
    0 — scanned cleanly (including the honest "no facts defined" case)
    1 — drift found
    2 — could not determine: bad root, or a facts file this parser could not read.
        NOT a pass. A drift detector's healthy output is silence, so a parse failure
        reported as 0 is indistinguishable from a clean run.

Note: uses a minimal YAML subset parser to avoid requiring PyYAML.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

from common import SKILL_ROOT, iter_md_files


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


KNOWN_FACT_KEYS = {"name", "pattern", "expected_value", "note"}


class FactsUnreadable(Exception):
    """The facts file could not be understood — as distinct from having no facts in it.

    This exception exists because the two used to be the same outcome. `load_facts` parses
    a deliberately narrow YAML subset, and every input outside that subset produced an
    empty list, which `sync` reported as "no facts defined" and exited 0 on. Three legal
    YAML inputs did exactly that: keys in a different order, flow style, and a trailing
    comment swallowed into the pattern. All three rendered as "no drift" — byte-for-byte
    what a healthy repo looks like — so a drift detector could be completely blind and
    indistinguishable from one finding nothing to report.
    """


def load_facts(path: Path) -> list[dict]:
    """Minimal YAML parser for the sync_facts.yaml format (list of facts with
    name/pattern/expected_value/note keys). Only supports this exact layout.

    Raises FactsUnreadable when the file has content under `facts:` that this parser
    could not turn into facts. The subset is narrow on purpose — full YAML would mean a
    third-party dependency in a plugin that promises pure stdlib — but a narrow parser is
    only safe while it admits what it could not read.
    """
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
        else:
            # Any other `key: value` line is recorded rather than discarded, so _validate
            # can name the offending key. Silently dropping it made the unknown-key guard
            # unreachable — a typo produced a fact with no pattern and the error blamed the
            # missing pattern instead of the typo that caused it. A guard that cannot fire
            # is not a guard.
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:(.*)$", stripped)
            if m:
                current[m.group(1)] = _strip_quotes(m.group(2).strip())
    if current is not None:
        if in_note:
            current["note"] = "\n".join(note_lines).strip()
        facts.append(current)
    _validate(text, facts, path)
    return facts


def _content_under_facts(text: str) -> bool:
    """Is there anything under `facts:` that was meant to be a fact?

    Blank lines and comments do not count — the shipped starter is exactly that, and it
    must keep loading as an honest empty list rather than an error.
    """
    seen_key = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("facts:"):
            seen_key = True
            continue
        if seen_key:
            return True
    return False


def _validate(text: str, facts: list, path: Path) -> None:
    """Refuse to return a plausible answer this parser is not entitled to.

    Each rule corresponds to a measured failure, not a hypothetical: reordered keys and
    flow style both yielded zero facts, a trailing comment was swallowed into the pattern
    producing a regex that is valid and can never match, and a typo'd key produced a fact
    with no pattern that was skipped in silence at scan time.
    """
    if _content_under_facts(text) and not facts:
        raise FactsUnreadable(
            f"{path.as_posix()} has content under `facts:` but none of it parsed. "
            f"This parser supports a narrow YAML subset: one fact per `- name:` entry, "
            f"with `name` FIRST, then `pattern`, `expected_value`, `note`; block style "
            f"only, no flow mappings. Returning zero facts here would have reported "
            f"'no drift', which is exactly what a healthy repo looks like.")

    for fact in facts:
        name = fact.get("name", "<unnamed>")
        unknown = set(fact) - KNOWN_FACT_KEYS
        if unknown:
            raise FactsUnreadable(
                f"fact {name!r} has unrecognised key(s): {sorted(unknown)}. Expected one "
                f"of {sorted(KNOWN_FACT_KEYS)} - a typo here would otherwise produce a "
                f"fact with no pattern, which is skipped in silence.")
        if not fact.get("pattern"):
            raise FactsUnreadable(
                f"fact {name!r} has no `pattern`; it could never match anything, and a "
                f"fact that cannot match is indistinguishable from one that found nothing.")
        if "#" in fact["pattern"]:
            raise FactsUnreadable(
                f"fact {name!r} has `#` inside its pattern: {fact['pattern']!r}. If that "
                f"was a trailing comment, this parser swallowed it into the regex - the "
                f"result is still a valid pattern and can never match. Quote the value, or "
                f"move the comment to its own line.")


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
    try:
        facts = load_facts(Path(args.facts))
    except FactsUnreadable as e:
        # Exit 2, not 0 and not 1. This repo reserves 2 for "could not determine", and
        # "I could not read your facts file" is exactly that: it is neither a clean run
        # nor a drift finding, and reporting it as either loses the distinction the
        # three-valued-outcome invariant exists to keep.
        print(f"cannot determine: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"cannot determine: cannot read {args.facts}: {e}", file=sys.stderr)
        return 2

    print(f"CMS sync: scanning {root}")
    # Printed on every run, including the zero case. A count that only appears when it is
    # non-zero cannot be used to notice that it is zero, which is the number that matters.
    print(f"  Facts loaded: {len(facts)}")
    if not facts:
        print("  (no facts defined — add some to state/sync_facts.yaml; "
              "nothing can drift until you do)")
        print()
        return 0
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
    _utf8_stdio()
    sys.exit(main())
