"""Shared helpers for the loop-harness skill — pure stdlib, no third-party deps.

Resolves a state directory (overridable for tests via LOOP_HARNESS_STATE_DIR), reads/writes
small JSON state, appends per-run records to a cost log, and manages the "armed run" marker
that the safety hook keys off. Module name is prefixed `loop_` because crucible skill scripts
share a flat sys.path — `common`/`hook` are already taken by cms.
"""
from __future__ import annotations

import json
import subprocess
import os
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent  # skills/loop-harness/


def use_utf8_stdio() -> None:
    """Force UTF-8 on stdout/stderr before writing any non-ASCII.

    Windows consoles/pipes default to cp1252, which *raises UnicodeEncodeError* on the
    arrows/dashes in our reports — killing the process and destroying the exit-code contract
    (a sweep would exit 1 "red" when it actually meant 2 "unparsed"). Call once at each CLI
    entry point. Idempotent; a no-op on streams that don't support reconfigure.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # py3.7+
        except (AttributeError, ValueError):      # already-wrapped / detached stream
            pass

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

# A deliberate copy of crucible_common.run_bounded: a skill directory must work on its own
# when installed for Codex or Pi, so it cannot import the plugin's scripts/. Keep the two
# in step — tests/test_bounded_run.py exercises both.
# Running the PROJECT's code (tests, gate commands, checks, a dry run) can hang or run away:
# a planted mutant loops forever appending to a list. subprocess.run(timeout=) then kills
# only the direct child — `uv`, `sh`, `claude` — and the real worker, a grandchild, keeps
# running, orphaned. Two such orphans once grew to ~100 GB each and froze the machine. So:
#   - every child gets its own session (POSIX) / process group (Windows);
#   - on timeout, or when the tree's resident memory passes a cap, the whole tree is killed:
#     the group, plus every descendant found while the parent was still alive (a tool may
#     start its own group), and then reaped;
#   - after a normal exit, anything the command left running in its group is killed too.
# The memory cap is a watchdog, not an rlimit: macOS does not enforce RLIMIT_AS.
# CRUCIBLE_MEM_LIMIT_MB sets it (default 8192; 0 disables).

# Running the PROJECT's code (tests, gate commands, checks, a dry run) can hang or run away:
# a planted mutant loops forever appending to a list. subprocess.run(timeout=) then kills
# only the direct child — `uv`, `sh`, `claude` — and the real worker, a grandchild, keeps
# running, orphaned. Two such orphans once grew to ~100 GB each and froze the machine. So:
#   - every child gets its own session (POSIX) / process group (Windows);
#   - on timeout, or when the tree's resident memory passes a cap, the whole tree is killed:
#     the group, plus every descendant found while the parent was still alive (a tool may
#     start its own group), and then reaped;
#   - after a normal exit, anything the command left running in its group is killed too.
# The memory cap is a watchdog, not an rlimit: macOS does not enforce RLIMIT_AS. It is a
# ceiling for a RUNAWAY — normal test runs use megabytes — and it is relative to the machine:
# min(8 GB, a quarter of physical RAM), so a 16 GB laptop stops a runaway at 4 GB, long
# before it can take the machine. CRUCIBLE_MEM_LIMIT_MB overrides it (0 disables).

DEFAULT_MEM_LIMIT_MB = 8192
RAM_FRACTION = 4          # the cap is at most 1/RAM_FRACTION of physical memory


def physical_memory_mb() -> int | None:
    import os
    try:
        return int(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        return None


def default_mem_limit_mb() -> int:
    phys = physical_memory_mb()
    return min(DEFAULT_MEM_LIMIT_MB, phys // RAM_FRACTION) if phys else DEFAULT_MEM_LIMIT_MB


class Bounded:
    """The outcome of a bounded run. `killed` is "", "timeout" or "memory"."""

    def __init__(self, returncode: int, stdout: str, stderr: str, killed: str = "",
                 peak_mb: int = 0) -> None:
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr
        self.killed, self.peak_mb = killed, peak_mb


def mem_limit_mb() -> int:
    import os
    raw = os.environ.get("CRUCIBLE_MEM_LIMIT_MB")
    if raw is None:
        return default_mem_limit_mb()
    try:
        return max(0, int(raw))
    except ValueError:
        return default_mem_limit_mb()


def _ps_table() -> list[tuple[int, int, int, int]]:
    """(pid, ppid, pgid, rss_kb) for every process — POSIX `ps`, which macOS and Linux share."""
    try:
        p = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,rss="], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = []
    for line in p.stdout.splitlines():
        parts = line.split()
        if len(parts) == 4 and all(x.lstrip("-").isdigit() for x in parts):
            rows.append(tuple(int(x) for x in parts))
    return rows


def tree_of(root: int, table: list[tuple[int, int, int, int]] | None = None) -> set[int]:
    """`root`, its process group, and every descendant by parent link."""
    table = _ps_table() if table is None else table
    found = {root} | {pid for pid, _pp, pg, _r in table if pg == root}
    changed = True
    while changed:
        changed = False
        for pid, ppid, _pg, _r in table:
            if ppid in found and pid not in found:
                found.add(pid)
                changed = True
    return found


KILL_GRACE = 2.0   # seconds between SIGTERM and SIGKILL


def _kill_tree(proc) -> None:
    """SIGTERM to the group and every descendant, a short grace so test runners can clean
    up, then SIGKILL to whatever is left. The descendant set is taken while the parent is
    still alive — once it dies, its children are re-parented and the link is gone."""
    import os
    import signal
    import time
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        return
    pids = tree_of(proc.pid) - {os.getpid()}

    def send(sig) -> None:
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            pass
        for pid in pids:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass

    send(signal.SIGTERM)
    end = time.monotonic() + KILL_GRACE
    while time.monotonic() < end and proc.poll() is None:
        time.sleep(0.05)
    send(signal.SIGKILL)


def run_bounded(cmd, cwd: Path | str | None, timeout: float, *, shell: bool = False,
                env: dict | None = None, input_bytes: bytes | None = None,
                mem_limit: int | None = None) -> Bounded:
    """Run `cmd` (argv list, or a string with shell=True) with a hard wall-clock limit and a
    memory watchdog over its whole process tree; never leaves anything running behind it.
    returncode is -1 when the run was killed (see `.killed`). Raises OSError if it cannot start."""
    import time
    limit = mem_limit_mb() if mem_limit is None else mem_limit
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, cwd=None if cwd is None else str(cwd), env=env, shell=shell,
                            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    deadline = time.monotonic() + timeout
    killed, peak, out, err = "", 0, b"", b""
    first = True
    while True:
        try:
            out, err = proc.communicate(input=input_bytes if first else None,
                                        timeout=min(1.0, max(0.05, deadline - time.monotonic())))
            break
        except subprocess.TimeoutExpired:
            first = False
        if limit and sys.platform != "win32":
            table = _ps_table()
            members = tree_of(proc.pid, table)
            rss_mb = sum(r for pid, _pp, _pg, r in table if pid in members) // 1024
            peak = max(peak, rss_mb)
            if rss_mb > limit:
                killed = "memory"
        if not killed and time.monotonic() >= deadline:
            killed = "timeout"
        if killed:
            _kill_tree(proc)
            try:
                out, err = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                # something escaped the tree (a double-forked daemon) and still holds the
                # pipe: stop waiting rather than hang the caller on it
                proc.kill()
                for stream in (proc.stdout, proc.stderr):
                    try:
                        stream.close()
                    except (OSError, AttributeError):
                        pass
                proc.wait(timeout=5)
                out, err = b"", b"[crucible] output lost: a descendant escaped and held the pipe"
            break
    if not killed and sys.platform != "win32":
        import os
        import signal
        try:                  # whatever the command left running in its own group
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    text_out = (out or b"").decode("utf-8", "replace")
    text_err = (err or b"").decode("utf-8", "replace")
    if killed:
        why = (f"killed after {timeout:.0f}s" if killed == "timeout"
               else f"killed at {peak} MB resident (cap {limit} MB, CRUCIBLE_MEM_LIMIT_MB)")
        text_err += f"\n[crucible] {why} — the whole process tree was stopped\n"
    return Bounded(-1 if killed else proc.returncode, text_out, text_err, killed, peak)
