#!/usr/bin/env python3
"""PreToolUse hook: lint a SKILL.md at the moment it is written.

`skill_lint.py` already runs in CI. This runs the same per-file checks one step earlier,
and the reason is measured rather than aesthetic: this repo compared asking an agent to
perform a check (caught 2/6) against having the harness execute it (caught 3/3). A CI-only
lint is the first placement. A hook is the second.

What it checks and what it does about it:

  - **ERROR blocks the write** (exit 2). Malformed or unterminated frontmatter, a missing
    name or description, a non-kebab name, a name that disagrees with its directory. All
    of these make a skill load wrongly or not at all, they are cheap to fix in the moment,
    and none of them is a judgement call.
  - **WARN is printed and allowed** (exit 0 with stderr). Token budget and unsanctioned
    keys. Blocking a write for being 40 tokens over budget would make it impossible to add
    a section in two edits, and a gate that fires mid-thought is one people learn to
    disable — this repo already records that lesson about staleness warnings.

Cross-skill overlap is deliberately NOT checked here. It needs the whole corpus, it is a
property of a pair rather than of the file being written, and it cannot be actioned in the
edit that triggers it. It stays in `skill_lint --strict` and in `/curate`.

Scope: files named SKILL.md under the roots in SKILL_LINT_ROOTS (OS-path-separated),
defaulting to the current working directory. Everything else is waved through, so editing
an unrelated project is never gated. Fails open on any internal error: a broken hook must
not become a broken editor.

Exit codes (the Claude Code hook contract):
    0 — allow the write (stderr, if any, is advisory)
    2 — block the write; stderr is returned to the model as feedback
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

from skill_lint import ERROR, lint_text  # noqa: E402


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


def in_scope(path: Path) -> bool:
    """True when `path` sits under a configured root. Mirrors the cms hook's scoping, so
    a contributor sets one convention rather than two."""
    roots_env = os.environ.get("SKILL_LINT_ROOTS")
    roots = ([Path(p).expanduser() for p in roots_env.split(os.pathsep) if p.strip()]
             if roots_env else [Path.cwd()])
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


def simulate_write(tool_name: str, tool_input: dict, existing: str) -> str | None:
    """The content the write would produce, or None when it cannot be determined.

    Returning None means "do not judge" — guessing at the resulting text and blocking on
    the guess would be worse than not checking, because the author cannot tell which
    document the complaint is about.
    """
    if tool_name == "Write":
        content = tool_input.get("content")
        return content if isinstance(content, str) else None
    if tool_name == "Edit":
        old, new = tool_input.get("old_string"), tool_input.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return None
        if tool_input.get("replace_all"):
            return existing.replace(old, new)
        # A non-unique old_string is a failing edit anyway; leave it to the tool to say so.
        return existing.replace(old, new, 1) if existing.count(old) == 1 else None
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        # Fail open: an unparseable payload is this hook's problem, not the author's.
        print(f"[skill-lint-hook] could not parse stdin: {e}", file=sys.stderr)
        return 0

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path")
    if not file_path or tool_name not in {"Write", "Edit"}:
        return 0

    path = Path(file_path)
    if path.name != "SKILL.md" or not in_scope(path):
        return 0

    existing = ""
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            existing = ""

    proposed = simulate_write(tool_name, tool_input, existing)
    if proposed is None:
        return 0

    try:
        _, findings = lint_text(proposed, path.parent.name, path.name)
    except Exception as e:  # noqa: BLE001 — a linter defect must not block an edit
        print(f"[skill-lint-hook] check failed, allowing the write: {e}", file=sys.stderr)
        return 0

    errors = [f for f in findings if f.level == ERROR]
    warns = [f for f in findings if f.level != ERROR]

    if errors:
        sys.stderr.write("skill-lint blocked this SKILL.md write:\n")
        for f in errors:
            sys.stderr.write(f"  - {f.message}\n")
        if warns:
            sys.stderr.write("Also worth fixing while you are here:\n")
            for f in warns:
                sys.stderr.write(f"  - {f.message}\n")
        sys.stderr.write(
            "\nThe frontmatter a runtime actually reads is `name` + `description`, and the\n"
            "name must equal the directory, because discovery is by directory.\n"
            "Full check: python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/skill_lint.py\" --strict\n"
        )
        return 2

    if warns:
        # Allowed, but said out loud. A budget overrun is real and worth knowing at the
        # moment it is introduced, when moving a section into references/ is still cheap.
        sys.stderr.write("skill-lint (not blocking):\n")
        for f in warns:
            sys.stderr.write(f"  - {f.message}\n")
    return 0


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
