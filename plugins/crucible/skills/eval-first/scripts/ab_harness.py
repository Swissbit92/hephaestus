"""Blind A/B rating harness — the match-or-beat-or-revert gate core.

Present each case's baseline vs. candidate response side-by-side with sides
randomised and arm labels hidden, collect the rater's pick, then tally win-rate
with an exact two-sided sign test and map it to a three-way gate decision:
flip (candidate better) / may-flip (parity) / do-NOT-flip (candidate worse).

Generic and dependency-free (stdlib only). The pure logic (pairing + tally +
significance + verdict) is unit-tested headless; `run_cli` is the thin shell.
Arms are labelled "baseline" (A) and "candidate" (B) by convention but the
labels are function parameters — this works for any A/B comparison of named
groups of (arm-A, arm-B) response pairs.

Generalised from prior eval-first work (an arm-blinded A/B acceptance gate).
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class BlindPair:
    case_id: str
    left: str
    right: str
    left_is: str  # "A" or "B" — which arm is on the left (hidden from the rater)
    meta: dict = field(default_factory=dict)


def make_blind_pairs(
    arm_a: Dict[str, str],
    arm_b: Dict[str, str],
    rng: Optional[random.Random] = None,
    meta: Optional[Dict[str, dict]] = None,
) -> List[BlindPair]:
    """Build blind pairs for every case_id present in BOTH arms.

    Side assignment (which arm is 'left') is randomised per pair so the rater
    can't infer the arm from position. ``rng`` is injectable for deterministic
    tests. Case order is also shuffled.
    """
    rng = rng or random.Random()
    meta = meta or {}
    ids = sorted(set(arm_a) & set(arm_b))
    rng.shuffle(ids)
    pairs: List[BlindPair] = []
    for cid in ids:
        a_on_left = rng.random() < 0.5
        pairs.append(BlindPair(
            case_id=cid,
            left=arm_a[cid] if a_on_left else arm_b[cid],
            right=arm_b[cid] if a_on_left else arm_a[cid],
            left_is="A" if a_on_left else "B",
            meta=meta.get(cid, {}),
        ))
    return pairs


def tally(pairs: List[BlindPair], picks: Dict[str, str]) -> dict:
    """Tally ratings. ``picks`` maps case_id -> 'left' | 'right' | 'tie' | 'skip'.

    Returns A/B win counts, A win-rate over decided pairs, and an exact two-sided
    sign-test p-value (probability of the observed split under 50/50, ties
    excluded).
    """
    a_wins = b_wins = ties = skipped = 0
    for p in pairs:
        choice = picks.get(p.case_id, "skip")
        if choice == "tie":
            ties += 1
        elif choice == "skip":
            skipped += 1
        elif choice == "left":
            (a_wins, b_wins) = (a_wins + 1, b_wins) if p.left_is == "A" else (a_wins, b_wins + 1)
        elif choice == "right":
            (a_wins, b_wins) = (a_wins + 1, b_wins) if p.left_is == "B" else (a_wins, b_wins + 1)
    decided = a_wins + b_wins
    return {
        "a_wins": a_wins,
        "b_wins": b_wins,
        "ties": ties,
        "skipped": skipped,
        "decided": decided,
        "a_win_rate": round(a_wins / decided, 4) if decided else None,
        "sign_test_p": _two_sided_sign_test(a_wins, b_wins),
    }


def _two_sided_sign_test(k1: int, k2: int) -> Optional[float]:
    """Exact two-sided binomial sign test p-value for a k1 vs k2 split (p=0.5)."""
    n = k1 + k2
    if n == 0:
        return None
    k = min(k1, k2)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return round(min(1.0, 2 * tail), 4)


def verdict(tally_result: dict, arm_a_label: str = "baseline", arm_b_label: str = "candidate",
            alpha: float = 0.05) -> str:
    """Map a tally to the match-or-beat-or-revert gate (candidate = arm B)."""
    rate = tally_result["a_win_rate"]
    if rate is None:
        return "no decided pairs"
    p = tally_result["sign_test_p"]
    sig = (p is not None and p < alpha)
    if not sig:
        return f"PARITY (no significant difference, p={p}) — candidate may flip"
    if rate < 0.5:
        return f"CANDIDATE BETTER ({arm_b_label} wins, p={p}) — flip"
    return f"CANDIDATE WORSE ({arm_a_label} wins, p={p}) — do NOT flip; fix or keep baseline"


# ----- thin interactive shell -----

def run_cli(pairs: List[BlindPair]) -> Dict[str, str]:  # pragma: no cover - interactive
    picks: Dict[str, str] = {}
    print(f"\nBlind A/B — {len(pairs)} pairs. For each: [l]eft / [r]ight / [t]ie / [s]kip / [q]uit\n")
    for i, p in enumerate(pairs, 1):
        ctx = f" ({p.meta.get('group', '')}/{p.meta.get('category', '')})" if p.meta else ""
        print(f"\n=== {i}/{len(pairs)} — case {p.case_id}{ctx} ===")
        print(f"\n[LEFT]\n{p.left}\n\n[RIGHT]\n{p.right}\n")
        choice = input("which is better? ").strip().lower()[:1]
        mapping = {"l": "left", "r": "right", "t": "tie", "s": "skip", "q": "quit"}
        sel = mapping.get(choice, "skip")
        if sel == "quit":
            break
        picks[p.case_id] = sel
    return picks


def save_ratings(path: Path | str, pairs: List[BlindPair], picks: Dict[str, str],
                 extra: Optional[dict] = None) -> None:  # pragma: no cover - io
    out = {
        "tally": tally(pairs, picks),
        "verdict": verdict(tally(pairs, picks)),
        "picks": picks,
        "pairs": [{"case_id": p.case_id, "left_is": p.left_is, **p.meta} for p in pairs],
        **(extra or {}),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=True)
