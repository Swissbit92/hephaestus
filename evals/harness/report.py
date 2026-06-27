"""Aggregate per-scenario criteria across k runs, decide the gate, and freeze/compare
baselines. Pure stdlib.

Gate model (deterministic-first):
  - A single run PASSES if all its DETERMINISTIC criteria pass. Judge criteria are advisory
    (recorded, not gated) unless a scenario sets gate_judge=true.
  - A scenario PASSES per its gate_mode:
      "all"  (default) -> pass^k : every one of the k runs passed   [safety/compliance]
      "rate" -> avg@k >= min_rate                                    [capability]
  - The suite PASSES if every scenario passes.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import reliability
from .model import Criterion


def _run_passed(criteria: list[Criterion], gate_judge: bool) -> bool:
    relevant = [c for c in criteria if c.kind == "deterministic" or (gate_judge and c.kind == "judge")]
    return bool(relevant) and all(c.passed for c in relevant)


def summarize_scenario(scenario: dict, runs: list[list[Criterion]]) -> dict:
    """`runs` is a list (one per repetition) of the Criterion list produced that run."""
    gate_judge = bool(scenario.get("gate_judge", False))
    gate_mode = scenario.get("gate_mode", "all")
    min_rate = float(scenario.get("min_rate", 1.0))

    run_pass = [_run_passed(c, gate_judge) for c in runs]
    avg = reliability.avg_at_k(run_pass)
    phat = reliability.pass_hat_k(run_pass)

    if gate_mode == "rate":
        passed = avg >= min_rate
    else:
        passed = phat

    # Per-criterion pass rate across runs (for debugging which criterion fails).
    per_criterion: dict[str, dict] = {}
    for c_list in runs:
        for c in c_list:
            d = per_criterion.setdefault(c.name, {"kind": c.kind, "passes": 0, "n": 0, "last_detail": ""})
            d["n"] += 1
            d["passes"] += 1 if c.passed else 0
            if not c.passed:
                d["last_detail"] = c.detail

    return {
        "id": scenario["id"],
        "skill": scenario.get("skill", ""),
        "kind": scenario.get("kind", "deterministic"),
        "gate_mode": gate_mode,
        "min_rate": min_rate,
        "k": len(runs),
        "run_pass": run_pass,
        "avg_at_k": round(avg, 4),
        "pass_hat_k": phat,
        "passed": passed,
        "criteria": per_criterion,
    }


def build_report(summaries: list[dict]) -> dict:
    total = len(summaries)
    passed = sum(1 for s in summaries if s["passed"])
    return {
        "suite_passed": passed == total and total > 0,
        "scenarios_passed": passed,
        "scenarios_total": total,
        "scenarios": summaries,
    }


def gate(report: dict) -> bool:
    return bool(report.get("suite_passed"))


def freeze_baseline(report: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True))
    return path


def compare_to_baseline(report: dict, baseline: dict) -> dict:
    """Per-scenario regressions vs a frozen baseline: scenarios that passed then and fail now."""
    base = {s["id"]: s["passed"] for s in baseline.get("scenarios", [])}
    regressions, improvements, new = [], [], []
    for s in report.get("scenarios", []):
        sid = s["id"]
        if sid not in base:
            new.append(sid)
        elif base[sid] and not s["passed"]:
            regressions.append(sid)
        elif not base[sid] and s["passed"]:
            improvements.append(sid)
    return {"regressions": regressions, "improvements": improvements, "new": new,
            "clean": not regressions}
