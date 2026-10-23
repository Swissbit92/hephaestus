"""Reliability math for stochastic candidate runs. Pure stdlib.

LLM-backed candidates are stochastic, so a case is run k times. We report:
  - avg@k     : mean per-run pass rate (expected per-run quality)
  - pass^k    : did ALL k runs pass — the reliability floor users actually feel
  - pass@k    : did ANY of the observed k runs pass — the capability ceiling
  - pass@k estimate : unbiased P(a random k-subset contains a pass), given n runs, c passes

Gate guidance (Anthropic "Demystifying Evals", 2026): pass^k for regression /
production gates (every attempt must hold); pass@k for capability evals (best-
case potential). A 75%/run candidate has pass@3 ~ 0.98 but pass^3 ~ 0.42 —
users live on the floor.
"""
from __future__ import annotations

from math import comb


def avg_at_k(runs: list[bool]) -> float:
    if not runs:
        return 0.0
    return sum(1 for r in runs if r) / len(runs)


def pass_hat_k(runs: list[bool]) -> bool:
    """All k runs passed (pass^k) — use for regression / production gates."""
    return len(runs) > 0 and all(runs)


def pass_any(runs: list[bool]) -> bool:
    """At least one of the observed runs passed (observed pass@k)."""
    return any(runs)


def pass_at_k_estimate(n: int, c: int, k: int) -> float:
    """Unbiased estimator (Chen et al. / HumanEval): probability that a random k-subset of
    n runs contains at least one of the c passing runs."""
    if k <= 0:
        raise ValueError("k must be positive")
    if k > n:
        raise ValueError("k cannot exceed n")
    if c <= 0:
        return 0.0
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


# --------------------------------------------------------------------------- resolution
# A pass rate is a measurement with an error bar, and on the case counts skill evals use
# (tens, not thousands) the bar is wide. These answer the two questions to ask BEFORE an
# A/B: how uncertain is a rate I have, and how many cases would it take to see the
# difference I care about? The Wilson interval is used rather than the normal
# approximation because the latter is too narrow for small n and collapses to zero width
# at 0% and 100% — exactly the rates a regression gate produces.

def wilson_interval(passes: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a pass rate of `passes` out of `n`."""
    from statistics import NormalDist
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0 <= passes <= n:
        raise ValueError("passes must be between 0 and n")
    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    p = passes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def required_n(p_base: float, delta: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Cases per arm to detect a pass-rate change of `delta` from `p_base` (two-sided,
    two-proportion). Detecting 10 points at a 70% baseline takes ~300 cases per arm — the
    reason a 1–2 point delta on 50 cases is noise."""
    from math import ceil
    from statistics import NormalDist
    p_new = p_base + delta
    if not (0 < p_base < 1 and 0 < p_new < 1) or delta == 0:
        raise ValueError("need 0 < p_base, p_base + delta < 1 and delta != 0")
    nd = NormalDist()
    z = nd.inv_cdf(1 - alpha / 2) + nd.inv_cdf(power)
    var = p_base * (1 - p_base) + p_new * (1 - p_new)
    return ceil(z * z * var / (delta * delta))


def deterministic_runs(outputs: list[str]) -> bool:
    """True when repeated runs of ONE case produced identical output. Then repeats measure
    nothing (temperature 0, a cache): replication must come from more cases, not more k."""
    return len(outputs) >= 2 and len(set(outputs)) == 1


def _main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="eval resolution: confidence interval / sample size")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("ci", help="Wilson interval for a pass rate")
    p.add_argument("--passes", type=int, required=True)
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--confidence", type=float, default=0.95)
    p = sub.add_parser("n", help="cases per arm to detect a delta")
    p.add_argument("--p", type=float, required=True, help="baseline pass rate, 0..1")
    p.add_argument("--delta", type=float, required=True, help="change to detect, e.g. 0.1")
    p.add_argument("--power", type=float, default=0.8)
    a = ap.parse_args(argv)
    if a.cmd == "ci":
        lo, hi = wilson_interval(a.passes, a.n, a.confidence)
        print(f"{a.passes}/{a.n} = {a.passes / a.n:.2f}, {a.confidence:.0%} CI [{lo:.2f}, {hi:.2f}]")
    elif a.cmd == "n":
        print(f"{required_n(a.p, a.delta, power=a.power)} cases per arm to detect "
              f"{a.delta:+.2f} from {a.p:.2f} at {a.power:.0%} power")
    else:
        ap.print_help()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
