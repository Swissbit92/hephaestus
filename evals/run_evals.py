#!/usr/bin/env python3
"""Run the hephaestus skill-eval suite.

For each scenario: build a throwaway git fixture, run the skill k times via the `claude`
CLI, score each run with the deterministic checks (plus optional judge criteria), then
aggregate and gate. Exits non-zero if the suite gate fails.

Usage:
    python3 evals/run_evals.py                       # all scenarios, k=3
    python3 evals/run_evals.py --scenario finish-branch/refuses-merge-on-red
    python3 evals/run_evals.py -k 5 --json report.json
    python3 evals/run_evals.py --baseline evals/baselines/main.json   # compare/freeze
    python3 evals/run_evals.py --judge                                # enable LLM judge criteria
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))  # make `harness` + `fixtures` importable when run directly

import fixtures  # noqa: E402
from harness import judge as judge_mod  # noqa: E402
from harness import report as report_mod  # noqa: E402
from harness import runner, scoring  # noqa: E402
from harness.model import Criterion  # noqa: E402


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


def make_cli_judge(model: str):
    """A judge_fn that calls the pinned Claude model via the CLI and returns its text."""
    def judge_fn(prompt: str) -> str:
        r = subprocess.run(
            ["claude", "--bare", "-p", prompt, "--settings", json.dumps({"model": model}),
             "--output-format", "json"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        )
        if r.returncode != 0:
            raise RuntimeError(f"judge CLI failed: {r.stderr[:200]}")
        return json.loads(r.stdout).get("result", "")
    return judge_fn


def _one_run(scenario: dict, model: str | None, judge_fn, bare: bool) -> tuple[list[Criterion], str, str, dict]:
    """One repetition in its own throwaway fixture: (criteria, model seen, CLI version, cost)."""
    plugin_root = REPO_ROOT / "plugins" / scenario["plugin"]
    with tempfile.TemporaryDirectory(prefix="eval-") as td:
        fixture_dir = fixtures.build(scenario["fixture"], Path(td) / "repo")
        env = {key: val.replace("{fixture}", str(fixture_dir))
               for key, val in (scenario.get("env") or {}).items()}
        # A scenario that spawns a subagent pays for two nested runs — the subagent
        # usually runs a whole test suite of its own — so it needs materially more
        # headroom than a single-agent scenario. Without it the run is cut short and
        # the result reads as "the subagent produced nothing", which is a claim about
        # the skill when it was really a claim about the clock.
        run = runner.run_skill(
            scenario["prompt"], fixture_dir, plugin_root,
            model=model, env=env, allowed_tools=scenario.get("allowed_tools"),
            timeout=scenario.get("timeout", runner.DEFAULT_TIMEOUT),
            bare=bare,
        )
        target_loaded = scenario["plugin"] in run.loaded_plugins
        criteria: list[Criterion] = [
            Criterion("plugin_loaded", "deterministic", target_loaded,
                      f"loaded={run.loaded_plugins} errors={run.plugin_errors}")
        ]
        for chk in scenario["checks"]:
            criteria.append(scoring.apply_check(chk["check"], run, chk.get("args")))
        if judge_fn:
            for jc in scenario.get("judge", []):
                criteria.append(judge_mod.judge_criterion(
                    jc["key"], jc["criterion"], jc["rubric"], run.final_text, judge_fn))
        perf = {"duration_ms": run.duration_ms, "cost_usd": run.cost_usd, "tokens": run.tokens}
        return criteria, run.model, run.cli_version, perf


def run_scenario(scenario: dict, k: int, model: str | None, judge_fn, bare=False,
                 jobs: int = 1) -> dict:
    """k repetitions, `jobs` at a time. Each repetition has its own fixture directory and
    its own CLI process, so they are independent; results keep repetition order, and the
    report's k is unchanged — a parallel run compares against a serial baseline."""
    if jobs > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(lambda _i: _one_run(scenario, model, judge_fn, bare), range(k)))
    else:
        results = [_one_run(scenario, model, judge_fn, bare) for _ in range(k)]
    runs = [r[0] for r in results]
    models = {r[1] for r in results if r[1]}
    cli_versions = {r[2] for r in results if r[2]}
    summary = report_mod.summarize_scenario(scenario, runs)
    summary["models"] = sorted(models)
    summary["cli_versions"] = sorted(cli_versions)
    summary["perf"] = report_mod.summarize_perf([r[3] for r in results])
    return summary


def develop_fix_cap() -> str:
    """The fix-round cap develop enforces at this plugin revision, read from the script that
    enforces it — not restated here, where it could drift. "unbounded" before the ledger
    existed: a baseline frozen then measured a workflow with no cap at all, and saying so
    is what makes a later comparison honest about what changed."""
    ledger = REPO_ROOT / "plugins" / "crucible" / "scripts" / "milestone_ledger.py"
    if not ledger.exists():
        return "unbounded"
    m = re.search(r"^DEFAULT_FIX_CAP\s*=\s*(\d+)", ledger.read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "unknown"


def plugin_revision() -> str:
    """HEAD plus a dirty marker for plugins/: the run measures the working tree, so a clean
    sha alone would misattribute numbers taken on uncommitted plugin edits."""
    def _git(*a: str) -> str:
        try:
            r = subprocess.run(["git", "-C", str(REPO_ROOT), *a], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return r.stdout.strip() if r.returncode == 0 else ""
    sha = _git("rev-parse", "--short", "HEAD") or "unknown"
    dirty = bool(_git("status", "--porcelain", "--", "plugins"))
    return f"{sha}{'+dirty' if dirty else ''}"


def build_meta(summaries: list[dict], k: int) -> dict:
    models = sorted({m for s in summaries for m in s.get("models", [])})
    versions = sorted({v for s in summaries for v in s.get("cli_versions", [])})
    return {
        "date": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d"),
        "k": k,
        "models": models,
        "cli_versions": versions,
        "plugin_revision": plugin_revision(),
        "develop_fix_cap": develop_fix_cap(),
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run the hephaestus skill-eval suite")
    ap.add_argument("--scenario", action="append",
                    help="run only this scenario id; repeat for several (default: all)")
    ap.add_argument("-k", type=int, default=3, help="runs per scenario (pass^k); default 3")
    ap.add_argument("--model", help="pin the model under test (e.g. claude-sonnet-4-6)")
    ap.add_argument("--bare", action="store_true",
                    help="hermetic run: ignore ~/.claude and authenticate via "
                         "ANTHROPIC_API_KEY. Required in CI, which has no logged-in "
                         "session; omit it locally to use your existing login for free")
    ap.add_argument("--judge", action="store_true", help="enable optional LLM-judge criteria")
    ap.add_argument("--jobs", type=int, default=1,
                    help="run up to N repetitions (and scenarios) at once; default 1")
    ap.add_argument("--json", help="write the full JSON report here")
    ap.add_argument("--baseline", help="baseline JSON: compare against it; freeze if absent")
    args = ap.parse_args(argv)

    if not runner.cli_available():
        print("error: `claude` CLI not found — the eval runner needs it.", file=sys.stderr)
        return 2

    scenarios = json.loads((HERE / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]
    if args.scenario:
        known = {s["id"] for s in scenarios}
        missing = [sid for sid in args.scenario if sid not in known]
        if missing:
            print(f"error: no scenario id {missing[0]!r}", file=sys.stderr)
            return 2
        scenarios = [s for s in scenarios if s["id"] in args.scenario]

    judge_fn = make_cli_judge(judge_mod.JUDGE_MODEL) if args.judge else None

    def _scenario(s: dict) -> dict:
        print(f"▶ {s['id']}  (k={args.k}) …", flush=True)
        return run_scenario(s, args.k, args.model, judge_fn, bare=args.bare,
                            jobs=max(1, args.jobs // max(1, len(scenarios))) if args.jobs > 1 else 1)

    if args.jobs > 1 and len(scenarios) > 1:
        # Scenarios in parallel too, sharing the job budget; output is printed in order.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(args.jobs, len(scenarios))) as pool:
            results = list(pool.map(_scenario, scenarios))
    else:
        results = [_scenario(s) for s in scenarios]

    summaries = []
    for s, summary in zip(scenarios, results):
        mark = "✔" if summary["passed"] else "✘"
        perf = summary.get("perf") or {}
        print(f"  {mark} {'PASS' if summary['passed'] else 'FAIL'}  "
              f"pass^k={summary['pass_hat_k']} avg={summary['avg_at_k']}  "
              f"median {perf.get('duration_ms_median')} ms · {perf.get('tokens_median')} tok · "
              f"${perf.get('cost_usd_median')}")
        if not summary["passed"]:
            for name, c in summary["criteria"].items():
                if c["passes"] < c["n"]:
                    print(f"      ✘ {name}: {c['passes']}/{c['n']} — {c['last_detail']}")
        summaries.append(summary)

    report = report_mod.build_report(summaries, meta=build_meta(summaries, args.k))
    print(f"\nSuite: {report['scenarios_passed']}/{report['scenarios_total']} scenarios passed")
    print(f"meta: {json.dumps(report['meta'], sort_keys=True)}")

    if args.json:
        report_mod.freeze_baseline(report, args.json)
        print(f"report written to {args.json}")

    if args.baseline:
        bpath = Path(args.baseline)
        if bpath.exists():
            cmp = report_mod.compare_to_baseline(report, json.loads(bpath.read_text(encoding="utf-8")))
            if not cmp["comparable"]:
                print(f"cannot compare to baseline: {cmp['reason']} — this is not a pass",
                      file=sys.stderr)
                return 2
            print(f"vs baseline: regressions={cmp['regressions']} improvements={cmp['improvements']} new={cmp['new']}")
            print(f"avg@k deltas: {json.dumps(cmp['avg_deltas'], sort_keys=True)}")
        else:
            report_mod.freeze_baseline(report, bpath)
            print(f"baseline frozen to {bpath}")

    return 0 if report_mod.gate(report) else 1


if __name__ == "__main__":
    _utf8_stdio()
    sys.exit(main(sys.argv[1:]))
