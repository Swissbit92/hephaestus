"""Budget & turn-ceiling accounting for loop-harness — pure stdlib.

The HARD ceiling is TURNS: the loop driver calls `charge` once per iteration, so the count is
deterministic and the loop cannot run away. Token and cost ceilings are OPTIONAL soft inputs
the driver supplies only when it has real usage data (an agent can't precisely meter its own
tokens — don't pretend otherwise).

Pure functions hold the math; a thin CLI (arm / charge / status / disarm) persists run state
via loop_common so the PreToolUse safety hook can tell whether a loop is armed.

CLI:
    python3 loop_budget.py arm --goal "..." --max-turns 20 [--max-tokens N] [--max-cost-usd X] [--worktree PATH]
    python3 loop_budget.py charge [--turns 1] [--tokens N] [--cost-usd X]   # exit 3 if over budget
    python3 loop_budget.py status
    python3 loop_budget.py disarm [--status converged|budget-exhausted|stopped]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import loop_common
import loop_ledger

EXIT_OVER_BUDGET = 3  # `charge`/`status` use this so the driver knows to stop


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run(
    goal: str,
    max_turns: int,
    *,
    max_tokens: int | None = None,
    max_cost_usd: float | None = None,
    worktree: str | None = None,
    ledger: str | None = None,
    run_id: str | None = None,
    started_at: str | None = None,
) -> dict:
    if int(max_turns) <= 0:
        raise ValueError("max_turns must be a positive integer")
    started = started_at or _now_iso()
    return {
        "run_id": run_id or f"loop-{started}",
        "goal": goal,
        "worktree": worktree,
        "ledger": ledger,
        "started_at": started,
        "max_turns": int(max_turns),
        "max_tokens": int(max_tokens) if max_tokens is not None else None,
        "max_cost_usd": float(max_cost_usd) if max_cost_usd is not None else None,
        "turns": 0,
        "tokens": 0,
        "cost_usd": 0.0,
    }


def charge(run: dict, *, turns: int = 1, tokens: int = 0, cost_usd: float = 0.0) -> dict:
    """Return a new run dict with counters incremented (does not mutate the input)."""
    updated = dict(run)
    updated["turns"] = run.get("turns", 0) + int(turns)
    updated["tokens"] = run.get("tokens", 0) + int(tokens)
    updated["cost_usd"] = round(run.get("cost_usd", 0.0) + float(cost_usd), 6)
    return updated


def check_budget(run: dict) -> tuple[bool, str]:
    """Return (ok, reason). ok is False once any configured ceiling is reached."""
    if run.get("turns", 0) >= run.get("max_turns", 0):
        return False, f"turn ceiling reached ({run.get('turns', 0)}/{run.get('max_turns', 0)})"
    mt = run.get("max_tokens")
    if mt is not None and run.get("tokens", 0) >= mt:
        return False, f"token ceiling reached ({run.get('tokens', 0)}/{mt})"
    mc = run.get("max_cost_usd")
    if mc is not None and run.get("cost_usd", 0.0) >= mc:
        return False, f"cost ceiling reached (${run.get('cost_usd', 0.0):.4f}/${mc:.4f})"
    return True, "within budget"


def remaining(run: dict) -> dict:
    out = {"turns": max(0, run.get("max_turns", 0) - run.get("turns", 0))}
    if run.get("max_tokens") is not None:
        out["tokens"] = max(0, run["max_tokens"] - run.get("tokens", 0))
    if run.get("max_cost_usd") is not None:
        out["cost_usd"] = max(0.0, round(run["max_cost_usd"] - run.get("cost_usd", 0.0), 6))
    return out


# --- CLI ---

def _cmd_arm(args) -> int:
    if loop_common.load_run() is not None:
        print("[loop-budget] a run is already armed; disarm first", file=sys.stderr)
        return 1
    ledger = args.ledger
    if ledger is None and args.worktree:
        ledger = os.path.join(args.worktree, "LOOP-STATE.md")  # convention
    run = new_run(
        args.goal,
        args.max_turns,
        max_tokens=args.max_tokens,
        max_cost_usd=args.max_cost_usd,
        worktree=args.worktree,
        ledger=ledger,
    )
    loop_common.save_json(loop_common.RUN_STATE_FILE, run)
    print(json.dumps({"armed": True, "run_id": run["run_id"], "remaining": remaining(run)}))
    return 0


def _cmd_charge(args) -> int:
    run = loop_common.load_run()
    if run is None:
        print("[loop-budget] no armed run", file=sys.stderr)
        return 1
    run = charge(run, turns=args.turns, tokens=args.tokens, cost_usd=args.cost_usd)
    loop_common.save_json(loop_common.RUN_STATE_FILE, run)
    ok, reason = check_budget(run)
    print(json.dumps({"ok": ok, "reason": reason, "run_id": run["run_id"], "remaining": remaining(run)}))
    return 0 if ok else EXIT_OVER_BUDGET


def _cmd_status(args) -> int:
    run = loop_common.load_run()
    if run is None:
        print(json.dumps({"armed": False}))
        return 0
    ok, reason = check_budget(run)
    print(json.dumps({
        "armed": True, "ok": ok, "reason": reason, "run_id": run["run_id"],
        "spent": {"turns": run.get("turns", 0), "tokens": run.get("tokens", 0), "cost_usd": run.get("cost_usd", 0.0)},
        "remaining": remaining(run),
    }))
    return 0 if ok else EXIT_OVER_BUDGET


def _sync_ledger_status(run: dict) -> bool:
    """Stamp the run's final status into its ledger so it stops reading 'armed'. No-op if the
    ledger path is unknown or missing."""
    path = run.get("ledger")
    if not path or not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = loop_ledger.set_status(text, run.get("final_status", "stopped"), updated=run.get("ended_at"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return True


def disarm_run(run: dict, status: str) -> dict:
    """Finalize an armed run: stamp end + status, append a cost-log record, sync the ledger
    status, and clear the armed marker. Returns the finalized run (with `ledger_synced`).
    Shared by the `disarm` CLI and the loop_sweep driver."""
    run = dict(run)
    run["ended_at"] = _now_iso()
    run["final_status"] = status
    loop_common.append_cost_log(run)
    run["ledger_synced"] = _sync_ledger_status(run)
    loop_common.clear_state(loop_common.RUN_STATE_FILE)
    return run


def _cmd_disarm(args) -> int:
    run = loop_common.load_run()
    if run is None:
        print("[loop-budget] no armed run", file=sys.stderr)
        return 1
    run = disarm_run(run, args.status)
    print(json.dumps({"disarmed": True, "run_id": run["run_id"], "final_status": run["final_status"], "ledger_synced": run["ledger_synced"]}))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="loop_budget", description="loop-harness budget/turn-ceiling accounting")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_arm = sub.add_parser("arm", help="start a bounded run")
    p_arm.add_argument("--goal", required=True)
    p_arm.add_argument("--max-turns", type=int, required=True, dest="max_turns")
    p_arm.add_argument("--max-tokens", type=int, default=None, dest="max_tokens")
    p_arm.add_argument("--max-cost-usd", type=float, default=None, dest="max_cost_usd")
    p_arm.add_argument("--worktree", default=None)
    p_arm.add_argument("--ledger", default=None, help="LOOP-STATE.md path (defaults to <worktree>/LOOP-STATE.md)")
    p_arm.set_defaults(func=_cmd_arm)

    p_charge = sub.add_parser("charge", help="record turns/tokens/cost; exit 3 if over budget")
    p_charge.add_argument("--turns", type=int, default=1)
    p_charge.add_argument("--tokens", type=int, default=0)
    p_charge.add_argument("--cost-usd", type=float, default=0.0, dest="cost_usd")
    p_charge.set_defaults(func=_cmd_charge)

    p_status = sub.add_parser("status", help="print remaining budget (exit 3 if exhausted)")
    p_status.set_defaults(func=_cmd_status)

    p_disarm = sub.add_parser("disarm", help="end the run and append a cost-log record")
    p_disarm.add_argument("--status", default="stopped")
    p_disarm.set_defaults(func=_cmd_disarm)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
