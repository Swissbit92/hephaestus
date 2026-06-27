#!/usr/bin/env python3
"""Run the whetstone skill-eval suite.

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
import json
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


def make_cli_judge(model: str):
    """A judge_fn that calls the pinned Claude model via the CLI and returns its text."""
    def judge_fn(prompt: str) -> str:
        r = subprocess.run(
            ["claude", "--bare", "-p", prompt, "--settings", json.dumps({"model": model}),
             "--output-format", "json"],
            capture_output=True, text=True, timeout=180,
        )
        if r.returncode != 0:
            raise RuntimeError(f"judge CLI failed: {r.stderr[:200]}")
        return json.loads(r.stdout).get("result", "")
    return judge_fn


def run_scenario(scenario: dict, k: int, model: str | None, judge_fn) -> dict:
    plugin_root = REPO_ROOT / "plugins" / scenario["plugin"]
    runs: list[list[Criterion]] = []
    for i in range(k):
        with tempfile.TemporaryDirectory(prefix="eval-") as td:
            fixture_dir = fixtures.build(scenario["fixture"], Path(td) / "repo")
            env = {key: val.replace("{fixture}", str(fixture_dir))
                   for key, val in (scenario.get("env") or {}).items()}
            run = runner.run_skill(
                scenario["prompt"], fixture_dir, plugin_root,
                model=model, env=env, allowed_tools=scenario.get("allowed_tools"),
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
            runs.append(criteria)
    return report_mod.summarize_scenario(scenario, runs)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Run the whetstone skill-eval suite")
    ap.add_argument("--scenario", help="run only this scenario id (default: all)")
    ap.add_argument("-k", type=int, default=3, help="runs per scenario (pass^k); default 3")
    ap.add_argument("--model", help="pin the model under test (e.g. claude-sonnet-4-6)")
    ap.add_argument("--judge", action="store_true", help="enable optional LLM-judge criteria")
    ap.add_argument("--json", help="write the full JSON report here")
    ap.add_argument("--baseline", help="baseline JSON: compare against it; freeze if absent")
    args = ap.parse_args(argv)

    if not runner.cli_available():
        print("error: `claude` CLI not found — the eval runner needs it.", file=sys.stderr)
        return 2

    scenarios = json.loads((HERE / "scenarios.json").read_text())["scenarios"]
    if args.scenario:
        scenarios = [s for s in scenarios if s["id"] == args.scenario]
        if not scenarios:
            print(f"error: no scenario id {args.scenario!r}", file=sys.stderr)
            return 2

    judge_fn = make_cli_judge(judge_mod.JUDGE_MODEL) if args.judge else None

    summaries = []
    for s in scenarios:
        print(f"▶ {s['id']}  (k={args.k}) …", flush=True)
        summary = run_scenario(s, args.k, args.model, judge_fn)
        mark = "✔" if summary["passed"] else "✘"
        print(f"  {mark} {'PASS' if summary['passed'] else 'FAIL'}  "
              f"pass^k={summary['pass_hat_k']} avg={summary['avg_at_k']}")
        if not summary["passed"]:
            for name, c in summary["criteria"].items():
                if c["passes"] < c["n"]:
                    print(f"      ✘ {name}: {c['passes']}/{c['n']} — {c['last_detail']}")
        summaries.append(summary)

    report = report_mod.build_report(summaries)
    print(f"\nSuite: {report['scenarios_passed']}/{report['scenarios_total']} scenarios passed")

    if args.json:
        report_mod.freeze_baseline(report, args.json)
        print(f"report written to {args.json}")

    if args.baseline:
        bpath = Path(args.baseline)
        if bpath.exists():
            cmp = report_mod.compare_to_baseline(report, json.loads(bpath.read_text()))
            print(f"vs baseline: regressions={cmp['regressions']} improvements={cmp['improvements']} new={cmp['new']}")
        else:
            report_mod.freeze_baseline(report, bpath)
            print(f"baseline frozen to {bpath}")

    return 0 if report_mod.gate(report) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
