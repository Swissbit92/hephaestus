"""Shared data types for the eval harness. Pure stdlib."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    name: str
    input: dict = field(default_factory=dict)


@dataclass
class WorldSnapshot:
    """A capture of the fixture's git + file state. The live runner builds these
    (world.py); scorers compare them. Kept plain so tests construct them by hand."""
    branch: str = ""
    head: str = ""
    commits: list[str] = field(default_factory=list)   # subjects, newest first
    dirty: bool = False
    branches: list[str] = field(default_factory=list)
    remote_head: str | None = None                     # tip of the tracked remote branch
    files: dict[str, str] = field(default_factory=dict)  # relpath -> content hash


@dataclass
class RunResult:
    """Everything one skill run produced, enough to score it without re-running."""
    plugin_loaded: bool = False
    loaded_plugins: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    plugin_errors: list = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_text: str = ""
    exit_ok: bool = True
    fixture_path: str = ""   # the run's working dir, for checks that read file content
    before: WorldSnapshot | None = None
    after: WorldSnapshot | None = None


@dataclass
class Criterion:
    name: str
    kind: str            # "deterministic" | "judge"
    passed: bool
    detail: str = ""
