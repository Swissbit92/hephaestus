"""Shared data types for the eval harness. Pure stdlib."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    name: str
    input: dict = field(default_factory=dict)
    turn: int = 1            # which user turn made the call (a scenario's `followup` is turn 2)


@dataclass
class ToolResult:
    """What a tool returned. For an Agent/Task call this is the subagent's OWN output — the
    thing to assert on when a subagent's verdict is the behaviour under test. The
    orchestrator's `final_text` is only a paraphrase of it, and paraphrases vary run to run,
    so gating on them measures the retelling rather than the verdict."""
    name: str
    text: str = ""


@dataclass
class WorldSnapshot:
    """A capture of the fixture's git + file state. The live runner builds these
    (world.py); scorers compare them. Kept plain so tests construct them by hand."""
    branch: str = ""
    head: str = ""
    commits: list[str] = field(default_factory=list)   # subjects, newest first
    dirty: bool = False
    branches: list[str] = field(default_factory=list)
    # Digest of every ref on the ACTUAL remote (git ls-remote), not a tracking ref.
    # A tracking ref moves on fetch as well as push, and the old field also keyed on
    # whichever branch was checked out, so switching branches read as a push.
    remote_state: str | None = None
    files: dict[str, str] = field(default_factory=dict)  # relpath -> content hash


@dataclass
class RunResult:
    """Everything one skill run produced, enough to score it without re-running."""
    plugin_loaded: bool = False
    loaded_plugins: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    plugin_errors: list = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    final_text: str = ""
    exit_ok: bool = True
    fixture_path: str = ""   # the run's working dir, for checks that read file content
    # What actually ran, from the CLI's init event — not the --model flag, which defaults
    # to None and so says nothing about the model a baseline was frozen against.
    model: str = ""
    cli_version: str = ""
    # Cost of the run, from the CLI's result event. None — never 0 — when the event is
    # missing (a timeout ends the stream before it), so an absent measure cannot average
    # in as "free". duration_ms always has a value: the runner's own clock is the fallback.
    duration_ms: int | None = None
    cost_usd: float | None = None
    tokens: dict | None = None        # input / output / cache_read / cache_creation
    num_turns: int | None = None
    subagents: int | None = None
    before: WorldSnapshot | None = None
    after: WorldSnapshot | None = None


@dataclass
class Criterion:
    name: str
    kind: str            # "deterministic" | "judge"
    passed: bool
    detail: str = ""
