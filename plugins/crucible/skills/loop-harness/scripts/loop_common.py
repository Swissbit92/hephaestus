"""Shared helpers for the loop-harness skill — pure stdlib, no third-party deps.

Resolves a state directory (overridable for tests via LOOP_HARNESS_STATE_DIR), reads/writes
small JSON state, appends per-run records to a cost log, and manages the "armed run" marker
that the safety hook keys off. Module name is prefixed `loop_` because crucible skill scripts
share a flat sys.path — `common`/`hook` are already taken by cms.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent  # skills/loop-harness/

# The armed-run marker: its presence means a loop is currently armed and the safety hook
# should enforce read-only/no-merge. Absence means normal manual work — hook stays inert.
RUN_STATE_FILE = "run.json"
COST_LOG_FILE = "cost-log.jsonl"  # append-only, one JSON record per finished run


def _resolve_state_dir() -> Path:
    override = os.environ.get("LOOP_HARNESS_STATE_DIR")
    if override:
        d = Path(override).expanduser()
    elif os.environ.get("CLAUDE_PLUGIN_DATA"):
        d = Path(os.environ["CLAUDE_PLUGIN_DATA"]).expanduser() / "loop-harness-state"
    else:
        d = SKILL_ROOT / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


STATE_DIR = _resolve_state_dir()


def _state_path(name: str) -> Path:
    return STATE_DIR / name


def load_json(name: str) -> dict | None:
    p = _state_path(name)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_json(name: str, data: dict) -> None:
    _state_path(name).write_text(
        json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
    )


def clear_state(name: str) -> None:
    p = _state_path(name)
    if p.exists():
        p.unlink()


def append_cost_log(record: dict) -> None:
    with _state_path(COST_LOG_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")


# --- armed-run helpers (the safety hook reads these) ---

def run_file_path() -> Path:
    return _state_path(RUN_STATE_FILE)


def load_run() -> dict | None:
    """Return the armed-run state, or None if no loop is currently armed."""
    return load_json(RUN_STATE_FILE)


def is_armed() -> bool:
    return load_run() is not None
