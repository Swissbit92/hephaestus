#!/usr/bin/env python3
"""PreToolUse hook for CMS.

Fires on Write / Edit tool calls targeting *.md files. Reads the Claude Code
hook payload from stdin, simulates the proposed file content, and runs the
mechanical CMS checks (frontmatter presence + @path validity) on it.

Behavior:
  - exit 0: pass silently
  - exit 2: block the write; stderr goes to Claude as feedback
  - exit 0 with stderr: non-blocking info (not used here)

Scope: by default, enforces on .md files under the current working directory.
Override with the CMS_ROOTS env var (OS-path-separated list of directories) to
gate a fixed set of repos regardless of cwd.

Files outside the in-scope roots are waved through (so edits to unrelated
projects aren't gated). Only files under a docs/ directory are checked; files
in docs/archive/ are exempted.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SKILL_SCRIPTS))

from common import (  # noqa: E402
    find_atpath_imports,
    validate_frontmatter,
)

# Roots whose docs/*.md files are gated. Configurable via CMS_ROOTS
# (e.g. "~/projects/a:~/projects/b"); defaults to the current working directory.
_roots_env = os.environ.get("CMS_ROOTS")
if _roots_env:
    ECOSYSTEM_ROOTS = [Path(p).expanduser().resolve() for p in _roots_env.split(os.pathsep) if p.strip()]
else:
    ECOSYSTEM_ROOTS = [Path.cwd()]


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
    try:
        resolved = path.resolve()
    except Exception:
        return False
    for root in ECOSYSTEM_ROOTS:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def is_archive(path: Path) -> bool:
    return "/archive/" in str(path).replace("\\", "/")


def simulate_write(tool_name: str, tool_input: dict, existing: str) -> str | None:
    if tool_name == "Write":
        return tool_input.get("content", "")
    if tool_name == "Edit":
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        replace_all = tool_input.get("replace_all", False)
        if old == "":
            return existing  # no-op edit; validate existing content rather than skip
        if replace_all:
            return existing.replace(old, new)
        return existing.replace(old, new, 1)
    return None


def check_content(path: Path, content: str) -> list[str]:
    """Errors that should block this write.

    Delegates to `common.validate_frontmatter` — the same rules the linter runs — so the
    gate can no longer know *less* than the report. It previously carried its own copy and
    had drifted: an unterminated fence was reported as "Missing frontmatter", sending the
    author to add metadata that was already there.

    Only `error` findings block. A warning (an oversized `ai_summary`, a lapsed review
    date) is real but must not stop someone saving a file — a gate that fires mid-thought
    is one people switch off.
    """
    errors = [f.message for f in validate_frontmatter(content, path) if f.level == "error"]
    for raw, target in find_atpath_imports(content, path.parent):
        if not target.exists():
            errors.append(f"@{raw} points to missing file: {target}")
    return errors


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        # Can't parse payload — fail open so we don't block unrelated work
        print(f"[cms-hook] could not parse stdin: {e}", file=sys.stderr)
        return 0

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path")
    if not file_path or tool_name not in {"Write", "Edit"}:
        return 0
    path = Path(file_path)
    if path.suffix.lower() != ".md":
        return 0
    if not in_scope(path):
        return 0
    if is_archive(path):
        return 0

    existing = ""
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            existing = ""

    proposed = simulate_write(tool_name, tool_input, existing)
    if proposed is None:
        return 0

    errors = check_content(path, proposed)
    if not errors:
        return 0

    # Block. Exit 2 with stderr returns feedback to Claude.
    sys.stderr.write(
        "CMS hook blocked this .md edit. Fix these mechanical issues and retry:\n"
    )
    for e in errors:
        sys.stderr.write(f"  - {e}\n")
    tmpl = SKILL_SCRIPTS.parent / "templates" / "frontmatter.md"
    sys.stderr.write(
        "\nHelp:\n"
        f"  - Frontmatter template: {tmpl}\n"
        "  - Full standard + rationale: run `/crucible:cms`\n"
        "  - Hook scope: .md files under docs/ within CMS_ROOTS or cwd (CLAUDE/README/CHANGELOG exempted)\n"
    )
    return 2


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main())
