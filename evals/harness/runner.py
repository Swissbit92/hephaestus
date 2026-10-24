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
import time
from pathlib import Path

from . import world
from .model import RunResult, ToolCall, ToolResult

DEFAULT_ALLOWED = ["Bash", "Read", "Edit", "Write", "Glob", "Grep", "TodoWrite"]
DEFAULT_TIMEOUT = 240


def cli_available() -> bool:
    return shutil.which("claude") is not None


def _result_text(block: dict) -> str:
    """A tool_result's content is either a plain string or a list of content blocks."""
    c = block.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
    return ""


def _usage(ev: dict) -> dict:
    """Cost fields of a `result` event: {} when absent, so callers record None, never 0."""
    u = ev.get("usage") or {}
    out = {}
    if "duration_ms" in ev:
        out["duration_ms"] = int(ev["duration_ms"])
    if "total_cost_usd" in ev:
        out["cost_usd"] = float(ev["total_cost_usd"])
    if u:
        out["tokens"] = {"input": int(u.get("input_tokens", 0)),
                         "output": int(u.get("output_tokens", 0)),
                         "cache_read": int(u.get("cache_read_input_tokens", 0)),
                         "cache_creation": int(u.get("cache_creation_input_tokens", 0))}
    if "num_turns" in ev:
        out["num_turns"] = int(ev["num_turns"])
    spawned = (ev.get("subagent_stats") or {}).get("spawned")
    if spawned is not None:
        out["subagents"] = int(spawned)
    return out


def _parse_stream(stdout: str) -> tuple[bool, list[str], list[str], list, list[ToolCall],
                                        list[ToolResult], str, str, str, dict]:
    """Parse `--output-format stream-json` lines into (any_plugin_loaded, loaded_plugin_names,
    skills, errors, tool_calls, tool_results, final_text, model, cli_version, usage).

    Tool *results* arrive on `user` events and are matched back to the tool that produced them
    via tool_use_id. For an Agent/Task call that is the subagent's own output — what to assert
    on when a subagent's verdict is the behaviour under test, since `final_text` is only the
    orchestrator's paraphrase of it."""
    skills: list[str] = []
    errors: list = []
    loaded_plugins: list[str] = []
    plugin_loaded = False
    tool_calls: list[ToolCall] = []
    tool_results: list[ToolResult] = []
    id_to_name: dict[str, str] = {}
    final_text = ""
    model = ""
    cli_version = ""
    usage: dict = {}
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
            model = str(ev.get("model", "") or "")
            cli_version = str(ev.get("claude_code_version", "") or "")
        elif t == "assistant":
            for block in (ev.get("message", {}).get("content", []) or []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_calls.append(ToolCall(name=block.get("name", ""), input=block.get("input", {}) or {}))
                    if block.get("id"):
                        id_to_name[block["id"]] = block.get("name", "")
        elif t == "user":
            for block in (ev.get("message", {}).get("content", []) or []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    name = id_to_name.get(block.get("tool_use_id", ""), "")
                    tool_results.append(ToolResult(name=name, text=_result_text(block)))
        elif t == "result":
            final_text = ev.get("result", "") or final_text
            usage = _usage(ev)
    return (plugin_loaded, loaded_plugins, skills, errors, tool_calls, tool_results, final_text,
            model, cli_version, usage)


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
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=str(fixture_dir), env=run_env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        stdout = proc.stdout
        exit_ok = proc.returncode == 0
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        exit_ok = False

    (plugin_loaded, loaded_plugins, skills, errors,
     tool_calls, tool_results, final_text, model_seen, cli_version, usage) = _parse_stream(stdout)
    wall_ms = int((time.monotonic() - started) * 1000)
    after = world.snapshot(fixture_dir)

    return RunResult(
        plugin_loaded=plugin_loaded, loaded_plugins=loaded_plugins, skills=skills,
        plugin_errors=errors, tool_calls=tool_calls, tool_results=tool_results,
        final_text=final_text,
        exit_ok=exit_ok, fixture_path=str(fixture_dir),
        model=model_seen, cli_version=cli_version, before=before, after=after,
        duration_ms=usage.get("duration_ms", wall_ms), cost_usd=usage.get("cost_usd"),
        tokens=usage.get("tokens"), num_turns=usage.get("num_turns"),
        subagents=usage.get("subagents"),
    )
