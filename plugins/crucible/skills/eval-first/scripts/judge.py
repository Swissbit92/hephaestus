"""Blind A/B LLM judge with swap augmentation + pinned-judge guard. Pure logic.

Bias mitigations baked in (2026 best practice):
- Swap augmentation: every pair is judged in BOTH orderings; an order-dependent
  verdict is treated as a tie. Position bias causes 10-15pt swings and
  instruction-based "ignore order" has ~zero measured effect — swapping is the
  mitigation that works.
- Pinned judge: JUDGE_MODEL is pinned; a silent version bump shifts scores.
- No self-grading: assert_judge_distinct() refuses a judge from the same model
  family as the candidate (self-grading inflates scores 10-25%).

`judge_fn(prompt) -> str` is injected, so the pure logic is testable without a
network. judge_pairs() returns picks in the ab_harness format (left/right/tie),
which ab_harness.tally/verdict turn into the match-or-beat-or-revert decision.
"""
from __future__ import annotations

import json
from typing import Callable, Dict, List, Optional

from ab_harness import BlindPair

JUDGE_MODEL = "claude-sonnet-4-6"  # pinned — never float a -latest alias

_FAMILIES = ("claude", "gpt", "gemini", "llama", "mistral", "qwen", "grok", "deepseek")


def family(model_id: str) -> str:
    """Best-effort model-family extraction for the self-grading guard."""
    m = model_id.lower()
    for f in _FAMILIES:
        if f in m:
            return f
    return m.split("-")[0].split("/")[-1]


def assert_judge_distinct(judge_model: str, candidate_model: str) -> None:
    """Refuse a judge in the same family as the candidate (self-grading inflates scores)."""
    if family(judge_model) == family(candidate_model):
        raise ValueError(
            f"judge ({judge_model}) and candidate ({candidate_model}) share family "
            f"'{family(judge_model)}' — self-grading inflates scores; pin a different family.")


def build_ab_prompt(case_input: str, left: str, right: str, rubric: str) -> str:
    return (
        "You are a blind judge comparing two responses to the same input. You do not "
        "know which system produced which.\n\n"
        f"# Input\n{case_input}\n\n# Rubric\n{rubric}\n\n"
        f"# Response LEFT\n{left}\n\n# Response RIGHT\n{right}\n\n"
        "First reason briefly about how each meets the rubric. Then output ONLY a JSON "
        'object: {"choice": "left" | "right" | "tie", "reason": "<one sentence>"}. '
        "Do not prefer a response for being longer."
    )


def parse_ab_verdict(text: str) -> dict:
    """Tolerant: return the last valid JSON object whose 'choice' is left/right/tie."""
    best = None
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict) and obj.get("choice") in ("left", "right", "tie"):
                            best = obj
                    except Exception:
                        pass
                    start = -1
    return best or {"choice": "tie", "reason": "unparseable"}


def _to_pair_terms(choice: str, swapped: bool) -> str:
    """Map a left/right/tie judge choice to pair terms (pair.left vs pair.right).
    When swapped, the judge saw pair.right on the left, so left<->right invert."""
    if choice == "tie":
        return "tie"
    if not swapped:
        return choice
    return "right" if choice == "left" else "left"


def judge_pair(pair: BlindPair, case_input: str, rubric: str,
               judge_fn: Callable[[str], str]) -> str:
    """Judge a pair in BOTH orderings; order-dependent verdict -> tie.
    Returns 'left'|'right'|'tie' in pair terms (consumed by ab_harness.tally)."""
    c1 = parse_ab_verdict(judge_fn(build_ab_prompt(case_input, pair.left, pair.right, rubric)))["choice"]
    c2 = parse_ab_verdict(judge_fn(build_ab_prompt(case_input, pair.right, pair.left, rubric)))["choice"]
    v1 = _to_pair_terms(c1, swapped=False)
    v2 = _to_pair_terms(c2, swapped=True)
    return v1 if v1 == v2 else "tie"


def judge_pairs(pairs: List[BlindPair], rubric: str, judge_fn: Callable[[str], str],
                case_inputs: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Swap-augmented picks for every pair, keyed by case_id (ab_harness format)."""
    case_inputs = case_inputs or {}
    return {p.case_id: judge_pair(p, case_inputs.get(p.case_id, ""), rubric, judge_fn)
            for p in pairs}
