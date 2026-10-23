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


def build_report(summaries: list[dict], meta: dict | None = None) -> dict:
    """`meta` records what the numbers were measured AGAINST — model, CLI version, k, the
    plugin revision and the develop fix cap in force. Without it a frozen baseline is a
    set of pass rates with no conditions attached, and a later run under a different model
    or k compares as if it were the same experiment."""
    total = len(summaries)
    passed = sum(1 for s in summaries if s["passed"])
    report = {
        "suite_passed": passed == total and total > 0,
        "scenarios_passed": passed,
        "scenarios_total": total,
        "scenarios": summaries,
    }
    if meta is not None:
        report["meta"] = meta
    return report


def gate(report: dict) -> bool:
    return bool(report.get("suite_passed"))


def freeze_baseline(report: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


# The conditions two runs must share before their pass rates mean the same thing. The date,
# CLI version and plugin revision are recorded but deliberately NOT compared: the plugin
# revision is the thing under test, and the other two move on their own between runs.
COMPARABLE_META = ("k", "models")


def meta_mismatch(report: dict, baseline: dict) -> str:
    """'' when the two were measured under the same conditions, else the reason they were
    not. Meta present on one side only is a mismatch: a baseline whose conditions are
    unknown cannot be shown to match anything."""
    rm, bm = report.get("meta"), baseline.get("meta")
    if rm is None and bm is None:
        return ""
    if rm is None or bm is None:
        return "only one side records run meta (model, k)"
    for key in COMPARABLE_META:
        if rm.get(key) != bm.get(key):
            return f"{key} differs: baseline {bm.get(key)!r} vs run {rm.get(key)!r}"
    return ""


def compare_to_baseline(report: dict, baseline: dict) -> dict:
    """Per-scenario regressions vs a frozen baseline: scenarios that passed then and fail now.

    `comparable` is False when the two runs were measured under different conditions; the
    lists are still filled in, but a caller must not read them as a verdict. `avg_deltas`
    carries the avg@k movement, which pass/fail alone hides — a scenario that drops from
    1.0 to 0.67 still passes a rate gate at 0.6."""
    reason = meta_mismatch(report, baseline)
    base = {s["id"]: s for s in baseline.get("scenarios", [])}
    regressions, improvements, new = [], [], []
    avg_deltas: dict[str, float] = {}
    for s in report.get("scenarios", []):
        sid = s["id"]
        if sid not in base:
            new.append(sid)
            continue
        b = base[sid]
        if b["passed"] and not s["passed"]:
            regressions.append(sid)
        elif not b["passed"] and s["passed"]:
            improvements.append(sid)
        if "avg_at_k" in b and "avg_at_k" in s:
            avg_deltas[sid] = round(s["avg_at_k"] - b["avg_at_k"], 4)
    return {"regressions": regressions, "improvements": improvements, "new": new,
            "avg_deltas": avg_deltas, "comparable": not reason, "reason": reason,
            "clean": not regressions and not reason}
