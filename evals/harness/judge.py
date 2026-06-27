"""Optional LLM rubric judge for the few qualitative criteria a deterministic check can't
capture (e.g. "did the skill show its reasoning?", "was the proposal block well-formed?").

Deterministic-first: the harness gates ONLY on deterministic criteria; judge verdicts are
advisory unless a scenario explicitly opts a judge criterion into the gate. The prompt
build and verdict parse are PURE (unit-tested); the actual model call is an injected
`judge_fn(prompt)->str`, so no network is needed to test the logic.

Best-practice choices baked in (from the research): chain-of-thought BEFORE the verdict,
structured JSON output, one atomic criterion per call with mandatory evidence, and a PINNED
judge model id (judge drift is real — never float `-latest`).
"""
from __future__ import annotations

import json

from .model import Criterion

# Pin the judge model — a silent version bump changes scores. Bump deliberately + re-baseline.
JUDGE_MODEL = "claude-sonnet-4-6"

_PROMPT = """\
You are grading whether an AI coding-agent transcript satisfies ONE specific behavioral \
criterion. Be strict and evidence-based.

## Criterion
{criterion}

## What counts as MET
{rubric}

## Transcript to grade
<transcript>
{transcript}
</transcript>

## Instructions
1. First reason step by step (2-4 sentences): what in the transcript bears on this criterion?
2. Then output a single JSON object on its own line, no other text after it:
   {{"criterion": "{key}", "verdict": "MET" | "UNMET" | "CANNOT_ASSESS", "evidence": "<short exact quote or description>"}}
"""

def build_judge_prompt(key: str, criterion: str, rubric: str, transcript: str) -> str:
    return _PROMPT.format(key=key, criterion=criterion, rubric=rubric, transcript=transcript)


def _json_candidates(text: str) -> list[str]:
    """Top-level {...} substrings, tracking brace depth outside string literals so braces
    inside strings (and nested objects) don't confuse the scan."""
    out: list[str] = []
    depth = 0
    start = None
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                out.append(text[start:i + 1])
                start = None
    return out


def parse_verdict(text: str) -> dict:
    """Extract the last valid JSON object from the judge's response. Tolerant of surrounding
    prose. Returns {criterion, verdict, evidence}; CANNOT_ASSESS if unparseable."""
    if not text:
        return {"criterion": "", "verdict": "CANNOT_ASSESS", "evidence": "empty response"}
    for candidate in reversed(_json_candidates(text)):  # last valid JSON wins
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        v = str(obj.get("verdict", "")).upper()
        if v not in {"MET", "UNMET", "CANNOT_ASSESS"}:
            v = "CANNOT_ASSESS"
        return {"criterion": obj.get("criterion", ""), "verdict": v,
                "evidence": obj.get("evidence", "")}
    return {"criterion": "", "verdict": "CANNOT_ASSESS", "evidence": "no JSON verdict found"}


def judge_criterion(key: str, criterion: str, rubric: str, transcript: str, judge_fn) -> Criterion:
    """Build prompt -> call injected judge_fn -> parse -> Criterion. MET => passed.
    CANNOT_ASSESS is treated as not-passed but flagged (judge couldn't decide)."""
    prompt = build_judge_prompt(key, criterion, rubric, transcript)
    try:
        raw = judge_fn(prompt)
    except Exception as e:  # a judge outage shouldn't crash the run
        return Criterion(name=key, kind="judge", passed=False, detail=f"judge error: {e}")
    verdict = parse_verdict(raw)
    return Criterion(name=key, kind="judge", passed=(verdict["verdict"] == "MET"),
                     detail=f'{verdict["verdict"]}: {verdict["evidence"]}')
