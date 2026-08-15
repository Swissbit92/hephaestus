"""PreToolUse safety hook for loop-harness — pure stdlib.

INERT unless a loop is armed (loop_common.load_run() is not None) — so it never interferes with
normal manual work. While a loop IS armed it enforces the read-only / worktree-only contract a
CI-Sweeper-style loop must honor:
  - blocks git push / merge / rebase / reset --hard / branch -d|-D / worktree remove
  - blocks Write/Edit to paths outside the armed run's worktree (when a worktree is set)
Committing *inside* the worktree is allowed — that is how a loop drafts a fix.

Exit codes (Claude Code PreToolUse convention): 0 = allow, 2 = block (stderr shown to Claude).
Fails OPEN on a stdin parse error (a malformed payload shouldn't wedge the loop); fails CLOSED
(blocks) only on a positively-matched dangerous action while armed.
"""
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

import loop_common

_SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|\n]")
# git global options that consume the FOLLOWING token as their value, so we must skip both
# (otherwise `git -C <dir> push` would hide `push` behind the value `<dir>`).
_GIT_OPTS_WITH_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace",
                        "--exec-path", "--config-env"}
_ENV_ASSIGN = re.compile(r"^\w+=")


def _segments(command: str) -> list[str]:
    return [s.strip() for s in _SEGMENT_SPLIT.split(command) if s.strip()]


def _git_subcommand(tokens: list[str]) -> tuple[str | None, list[str]]:
    """If a shell segment is a git invocation, return (subcommand, args_after) — having skipped
    leading env assignments (FOO=bar) and git global options (-C <dir>, -c <kv>, --git-dir=…).
    Otherwise (None, [])."""
    i = 0
    while i < len(tokens) and _ENV_ASSIGN.match(tokens[i]):
        i += 1  # FOO=bar git ...
    if i >= len(tokens) or tokens[i] != "git":
        return None, []  # not a git command (e.g. `echo git push`)
    i += 1
    while i < len(tokens):
        tok = tokens[i]
        if tok in _GIT_OPTS_WITH_VALUE:
            i += 2  # global option + its value token
            continue
        if tok.startswith("-"):
            i += 1  # valueless global flag (-p, --paginate, --bare) or --opt=value form
            continue
        return tok, tokens[i + 1:]  # the subcommand + everything after it
    return None, []


def _dangerous_git(subcmd: str, args: list[str]) -> str:
    if subcmd == "push":
        return "git push (a loop must never push)"
    if subcmd == "merge":
        return "git merge (a loop must never merge)"
    if subcmd == "rebase":
        return "git rebase (history rewrite)"
    if subcmd == "reset" and "--hard" in args:
        return "git reset --hard (destructive)"
    if subcmd == "branch" and any(a in ("-d", "-D", "--delete") for a in args):
        return "git branch delete"
    if subcmd == "worktree" and args and args[0] == "remove":
        return "git worktree remove"
    return ""


def _check_bash(command: str) -> tuple[bool, str]:
    for seg in _segments(command):
        try:
            tokens = shlex.split(seg)
        except ValueError:
            tokens = seg.split()  # unbalanced quotes → best-effort tokenization
        subcmd, args = _git_subcommand(tokens)
        if subcmd is None:
            continue
        why = _dangerous_git(subcmd, args)
        if why:
            return True, why
    return False, ""


def _check_write(file_path: str, worktree: str | None) -> tuple[bool, str]:
    if not worktree:
        return False, ""  # no worktree set → can't scope paths; other guards still apply
    try:
        target = Path(file_path).resolve()
        root = Path(worktree).resolve()
    except (OSError, RuntimeError):
        return False, ""
    if target == root or target.is_relative_to(root):
        return False, ""
    return True, f"write outside the loop worktree ({worktree})"


def check_command(tool_name: str, tool_input: dict, run: dict | None) -> tuple[bool, str]:
    """Return (block, reason). block=True means deny the tool call. run is the armed-run
    state, or None when no loop is armed (in which case the hook is inert)."""
    if run is None:
        return False, ""
    if tool_name == "Bash":
        return _check_bash(str(tool_input.get("command", "")))
    if tool_name in ("Write", "Edit"):
        fp = tool_input.get("file_path")
        if fp:
            return _check_write(str(fp), run.get("worktree"))
    return False, ""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as e:  # fail open — a parse error shouldn't wedge the loop
        print(f"[loop-hook] could not parse stdin: {e}", file=sys.stderr)
        return 0
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    run = loop_common.load_run()
    if run is None and loop_common.run_file_path().exists():
        # The marker is present but unreadable — guards are inactive. Surface it rather than
        # silently disabling protection mid-loop.
        print("[loop-hook] WARNING: armed-run state exists but is unreadable; guards inactive", file=sys.stderr)
    block, reason = check_command(tool_name, tool_input, run)
    if block:
        print(
            f"[loop-hook] blocked: {reason}. A loop is armed (read-only / worktree-only).",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    loop_common.use_utf8_stdio()
    raise SystemExit(main())
