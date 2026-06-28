"""Read-only CI Sweeper driver for loop-harness — pure stdlib.

One command runs a single **read-only diagnostic sweep**: arm a bounded run, run the project's
test command, summarize the output (loop_logscan), record findings to the LOOP-STATE ledger,
and emit a needs-me report. It **never drafts fixes, commits, or merges** — diagnosis only.
Drafting a fix is the agent's triage step (a separate, human-/agent-driven follow-up).

This operationalizes the loop-harness primitive: instead of hand-assembling
arm → ledger → charge → test → logscan → disarm, you run one command (cron-friendly).

CLI:
    python3 loop_sweep.py --test-cmd "pytest" [--worktree DIR] [--goal TEXT]
                          [--max-turns N] [--ledger PATH] [--report PATH]
Exit: 0 = green, 1 = red (failures/errors), 2 = could not parse a summary / setup error.

Security / trust boundary: `--test-cmd` is run via the shell (`shell=True`) because a real test
command routinely needs shell features (`pytest && ruff`, env vars, globs). It is the
**operator's own configuration**, exactly like a Makefile target or CI `script:` line — NOT
untrusted external input. Do not feed `--test-cmd` from an untrusted source.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

import loop_budget
import loop_common
import loop_ledger
import loop_logscan

EXIT_GREEN, EXIT_RED, EXIT_UNPARSED = 0, 1, 2


def classify(summary: dict) -> tuple[str, int]:
    """Map a loop_logscan summary to (status, exit_code). Unparsed → not green: a sweeper must
    never report green from output it couldn't read."""
    if not summary.get("matched"):
        return "unparsed", EXIT_UNPARSED
    if summary.get("failed", 0) or summary.get("errors", 0):
        return "red", EXIT_RED
    return "green", EXIT_GREEN


def build_report(run: dict, summary: dict, status: str) -> str:
    """A short markdown needs-me report drawn from the sweep result."""
    icon = {"green": "✅", "red": "❌", "unparsed": "⚠️"}.get(status, "•")
    lines = [
        f"# CI Sweeper report {icon} {status.upper()}",
        "",
        f"- **Run:** {run.get('run_id')}",
        f"- **Goal:** {run.get('goal')}",
        f"- **Result:** {summary.get('summary') or '(no summary parsed)'}",
        f"- **Counts:** {summary.get('passed', 0)} passed · {summary.get('failed', 0)} failed · "
        f"{summary.get('errors', 0)} errors · {summary.get('skipped', 0)} skipped",
    ]
    failing = summary.get("failing_tests") or []
    if failing:
        lines += ["", "## Needs-me — failing", *[f"- {t}" for t in failing]]
    if status == "unparsed":
        lines += ["", "## Needs-me", "- Could not parse a test summary from the output — check `--test-cmd` "
                  "(e.g. a doubled `-q` → `-qq` suppresses the summary)."]
    if status == "green":
        lines += ["", "Nothing to do — suite green, no fixes drafted."]
    return "\n".join(lines) + "\n"


def run_sweep(*, test_cmd: str, goal: str | None = None, max_turns: int = 1,
              worktree: str | None = None, ledger_path: str | None = None,
              report_path: str | None = None) -> int:
    goal = goal or f"diagnose: {test_cmd}"
    if loop_common.load_run() is not None:
        print("[loop-sweep] a run is already armed; disarm first", file=sys.stderr)
        return EXIT_UNPARSED
    if ledger_path is None:
        ledger_path = os.path.join(worktree, "LOOP-STATE.md") if worktree else "LOOP-STATE.md"

    run = loop_budget.new_run(goal, max_turns, worktree=worktree, ledger=ledger_path)
    loop_common.save_json(loop_common.RUN_STATE_FILE, run)
    status = "stopped"
    try:
        with open(ledger_path, "w", encoding="utf-8") as f:
            f.write(loop_ledger.init_ledger(goal, run["run_id"]))
        run = loop_budget.charge(run, turns=1)
        loop_common.save_json(loop_common.RUN_STATE_FILE, run)

        # shell=True is intentional: test_cmd is operator-supplied config that needs shell
        # features (see the module docstring's trust-boundary note), not untrusted input.
        proc = subprocess.run(test_cmd, shell=True, cwd=worktree, capture_output=True, text=True)  # noqa: S602
        summary = loop_logscan.summarize(f"{proc.stdout}\n{proc.stderr}")
        status, code = classify(summary)

        text = open(ledger_path, encoding="utf-8").read()
        text = loop_ledger.append_entry(
            text, "finding", f"`{test_cmd}` → {summary.get('summary') or 'no summary parsed'} (exit {proc.returncode})")
        for t in summary.get("failing_tests", []):
            text = loop_ledger.append_entry(text, "needs-me", f"failing: {t}")
        if not summary.get("matched"):
            text = loop_ledger.append_entry(text, "needs-me", "could not parse a test summary — check --test-cmd")
        open(ledger_path, "w", encoding="utf-8").write(text)

        report = build_report(run, summary, status)
        if report_path:
            open(report_path, "w", encoding="utf-8").write(report)
        else:
            sys.stdout.write(report)
        return code
    finally:
        armed = loop_common.load_run()
        if armed is not None:
            loop_budget.disarm_run(armed, status)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="loop_sweep", description="read-only CI Sweeper diagnostic pass")
    parser.add_argument("--test-cmd", required=True, help="the project's test command, e.g. 'pytest'")
    parser.add_argument("--goal", default=None)
    parser.add_argument("--max-turns", type=int, default=1, dest="max_turns")
    parser.add_argument("--worktree", default=None, help="run the test command in this dir (read-only)")
    parser.add_argument("--ledger", default=None, dest="ledger")
    parser.add_argument("--report", default=None, dest="report", help="write the report here instead of stdout")
    args = parser.parse_args(argv)
    return run_sweep(
        test_cmd=args.test_cmd, goal=args.goal, max_turns=args.max_turns,
        worktree=args.worktree, ledger_path=args.ledger, report_path=args.report,
    )


if __name__ == "__main__":
    raise SystemExit(main())
