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
