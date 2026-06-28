"""Deterministic-first checks — Layer 1 of the eval cascade. Pure stdlib.

Cheap, exact, auditable checks (schema, regex, length, citation) that run on
every candidate output BEFORE any LLM judge call. Deterministic checks catch
30-60% of failures at ~zero cost and tell you exactly which rule failed; the
judge only runs on outputs that clear this layer.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Dict, List, Optional


def _non_empty(out, args):
    return bool(out and out.strip())


def _exact_match(out, args):
    return out == args["expected"]


def _contains(out, args):
    return args["needle"] in out


def _not_contains(out, args):
    return args["needle"] not in out


def _regex_match(out, args):
    return re.search(args["pattern"], out) is not None


def _regex_absent(out, args):
    return re.search(args["pattern"], out) is None


def _max_length(out, args):
    return len(out) <= args["n"]


def _min_length(out, args):
    return len(out) >= args["n"]


def _json_parses(out, args):
    try:
        json.loads(out)
        return True
    except Exception:
        return False


def _json_has_keys(out, args):
    try:
        obj = json.loads(out)
    except Exception:
        return False
    return isinstance(obj, dict) and all(k in obj for k in args["keys"])


_CITATION_RE = re.compile(r"https?://|\[\d+\]|\(\d{4}\)")


def _citation_present(out, args):
    return _CITATION_RE.search(out) is not None


CHECKS: Dict[str, Callable[[str, dict], bool]] = {
    "non_empty": _non_empty,
    "exact_match": _exact_match,
    "contains": _contains,
    "not_contains": _not_contains,
    "regex_match": _regex_match,
    "regex_absent": _regex_absent,
    "max_length": _max_length,
    "min_length": _min_length,
    "json_parses": _json_parses,
    "json_has_keys": _json_has_keys,
    "citation_present": _citation_present,
}


def apply_check(check: str, output: str, args: Optional[dict] = None) -> dict:
    """Run one check. Returns {check, passed, detail}. Raises KeyError on an
    unknown check or a missing required arg."""
    if check not in CHECKS:
        raise KeyError(f"unknown deterministic check: {check!r} (have: {sorted(CHECKS)})")
    args = args or {}
    try:
        passed = bool(CHECKS[check](output, args))
    except KeyError as e:
        raise KeyError(f"check {check!r} missing required arg {e}") from e
    return {"check": check, "passed": passed, "detail": "ok" if passed else "failed"}


def run_deterministic(output: str, checks: List[dict]) -> dict:
    """Run a list of {check, args} on output. Returns per-check results + all_passed.
    The cascade gate: if all_passed is False, skip the (expensive) LLM judge."""
    results = [apply_check(c["check"], output, c.get("args")) for c in checks]
    return {"results": results, "all_passed": all(r["passed"] for r in results)}
