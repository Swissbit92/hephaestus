"""Drive a crucible skill headlessly and capture what it did. LIVE — needs the `claude`
CLI (default) or the Claude Agent SDK; skipped in headless CI.

Flow per run: snapshot the fixture -> invoke the skill non-interactively in the fixture
cwd (loading the plugin under test) -> snapshot again -> return a RunResult carrying the
init metadata (plugin loaded? errors?), the captured tool calls, the final text, and the
before/after WorldSnapshots. Scorers (pure) then judge the RunResult.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import world
from .model import RunResult, ToolCall

DEFAULT_ALLOWED = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "TodoWrite"]
DEFAULT_TIMEOUT = 240


def cli_available() -> bool:
    return shutil.which("claude") is not None


def _parse_stream(stdout: str) -> tuple[bool, list[str], list[str], list, list[ToolCall], str]:
    """Parse `--output-format stream-json` lines into (any_plugin_loaded, loaded_plugin_names,
    skills, errors, tool_calls, final_text)."""
    skills: list[str] = []
    errors: list = []
    loaded_plugins: list[str] = []
    plugin_loaded = False
    tool_calls: list[ToolCall] = []
    final_text = ""
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            skills = ev.get("skills", []) or []
            errors = ev.get("plugin_errors", []) or []
            plugins = ev.get("plugins", []) or []
            loaded_plugins = [p.get("name", "") if isinstance(p, dict) else str(p) for p in plugins]
            plugin_loaded = bool(plugins) and not errors
        elif t == "assistant":
            for block in (ev.get("message", {}).get("content", []) or []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.append(ToolCall(name=block.get("name", ""), input=block.get("input", {}) or {}))
        elif t == "result":
            final_text = ev.get("result", "") or final_text
    return plugin_loaded, loaded_plugins, skills, errors, tool_calls, final_text


def run_skill(
    prompt: str,
    fixture_dir: Path | str,
    plugin_root: Path | str,
    *,
    model: str | None = None,
    allowed_tools: list[str] | None = None,
    env: dict | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    bare: bool = False,
) -> RunResult:
    """Run one skill invocation via the `claude` CLI. Raises RuntimeError if the CLI is
    absent (callers should guard with cli_available()).

    bare=False (default) uses the logged-in credentials + config. bare=True is hermetic
    (ignores ~/.claude) but then needs ANTHROPIC_API_KEY in env for auth — use that for CI.
    """
    if not cli_available():
        raise RuntimeError("claude CLI not available")
    fixture_dir = Path(fixture_dir)
    allowed = allowed_tools or DEFAULT_ALLOWED

    before = world.snapshot(fixture_dir)

    cmd = ["claude"]
    if bare:
        cmd.append("--bare")
    cmd += [
        "-p", prompt,
        "--plugin-dir", str(plugin_root),
        "--permission-mode", "acceptEdits",
        "--allowedTools", " ".join(allowed),
        "--output-format", "stream-json", "--verbose",
    ]
    if model:
        cmd += ["--settings", json.dumps({"model": model})]

    run_env = {**os.environ, **(env or {})}
    exit_ok = True
    stdout = ""
    try:
        proc = subprocess.run(cmd, cwd=str(fixture_dir), env=run_env,
                              capture_output=True, text=True, timeout=timeout)
        stdout = proc.stdout
        exit_ok = proc.returncode == 0
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        exit_ok = False

    plugin_loaded, loaded_plugins, skills, errors, tool_calls, final_text = _parse_stream(stdout)
    after = world.snapshot(fixture_dir)

    return RunResult(
        plugin_loaded=plugin_loaded, loaded_plugins=loaded_plugins, skills=skills,
        plugin_errors=errors, tool_calls=tool_calls, final_text=final_text,
        exit_ok=exit_ok, fixture_path=str(fixture_dir), before=before, after=after,
    )
