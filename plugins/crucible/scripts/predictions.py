#!/usr/bin/env python3
"""Record what a change is expected to do, then check later whether it did.

A repo accumulates changes that were all justified at the time. What it does not
accumulate is evidence about *whether the justifications were right* — because the
prediction is made in a commit message or a conversation, the outcome arrives weeks later
somewhere else, and nothing ever puts the two next to each other. The result is a codebase
whose every decision looked sound and whose overall direction nobody can evaluate.

This is the smallest thing that fixes that: a prediction is written down **before** the
change lands, in a falsifiable form, with the check that would settle it; later, the check
is run and the outcome recorded against the original words. The value is entirely in the
`wrong` verdicts — a mechanism that only ever confirms itself is measuring nothing.

Two rules the format enforces rather than requests:

- **A prediction needs a `--check`** — the command or observation that would settle it. A
  prediction with no check is a hope, and hopes are always graded as correct in hindsight.
- **`verify` will not accept a rewritten prediction.** The recorded text is immutable; the
  outcome is appended beside it. Editing the claim to match the result is the exact failure
  this exists to prevent, and it is the natural thing to do when the result is embarrassing.

Storage is an append-only JSONL file, `docs/predictions.jsonl` by default — text, diffable,
reviewable, and carried by the repo rather than by a service.

Exit codes:
    0 — the operation succeeded
    1 — record refused (missing check), or verify found no matching open prediction
    2 — could not determine: the store is unreadable or malformed. NOT a pass.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_STORE = "docs/predictions.jsonl"

# The verdicts a verification may return. "unclear" is first-class on purpose: forcing a
# binary answer onto an ambiguous outcome is how a record like this becomes fiction, and an
# honest "we could not tell" is itself a finding about the prediction's falsifiability.
VERDICTS = ("right", "wrong", "partial", "unclear")


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


def load(store: Path) -> list[dict]:
    """Every record, oldest first. Raises ValueError on a malformed line."""
    if not store.exists():
        return []
    out: list[dict] = []
    for n, line in enumerate(store.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{store}:{n} is not valid JSON: {e}") from e
    return out


def append(store: Path, record: dict) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    with store.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def open_predictions(records: list[dict]) -> dict[str, dict]:
    """id -> the prediction, for ids that have no outcome yet."""
    preds = {r["id"]: r for r in records if r.get("kind") == "prediction"}
    for r in records:
        if r.get("kind") == "outcome":
            preds.pop(r.get("id"), None)
    return preds


def cmd_record(a: argparse.Namespace, store: Path) -> int:
    if not a.check or not a.check.strip():
        print("refused: a prediction needs --check, the command or observation that would\n"
              "settle it. Without one it cannot be wrong, and a claim that cannot be wrong\n"
              "is not a prediction.", file=sys.stderr)
        return 1
    try:
        records = load(store)
    except ValueError as e:
        print(f"cannot determine: {e}", file=sys.stderr)
        return 2
    if any(r.get("id") == a.id for r in records):
        print(f"refused: {a.id!r} is already recorded — ids are immutable so an outcome "
              f"cannot be attached to a rewritten claim.", file=sys.stderr)
        return 1
    append(store, {"kind": "prediction", "id": a.id, "date": a.date,
                   "claim": a.claim, "check": a.check})
    print(f"recorded {a.id}")
    return 0


def cmd_verify(a: argparse.Namespace, store: Path) -> int:
    try:
        records = load(store)
    except ValueError as e:
        print(f"cannot determine: {e}", file=sys.stderr)
        return 2
    openp = open_predictions(records)
    if a.id not in openp:
        known = "already verified" if any(r.get("id") == a.id for r in records) else "not recorded"
        print(f"no open prediction {a.id!r} ({known}).", file=sys.stderr)
        return 1
    append(store, {"kind": "outcome", "id": a.id, "date": a.date,
                   "verdict": a.verdict, "evidence": a.evidence or ""})
    pred = openp[a.id]
    print(f"{a.id}: {a.verdict}\n  claimed: {pred['claim']}")
    return 0


def cmd_list(a: argparse.Namespace, store: Path) -> int:
    try:
        records = load(store)
    except ValueError as e:
        print(f"cannot determine: {e}", file=sys.stderr)
        return 2
    preds = [r for r in records if r.get("kind") == "prediction"]
    outcomes = {r["id"]: r for r in records if r.get("kind") == "outcome"}
    openp = open_predictions(records)

    if a.json:
        print(json.dumps({"predictions": preds, "outcomes": list(outcomes.values())}, indent=2))
        return 0

    if not preds:
        print(f"no predictions recorded in {store.as_posix()}")
        return 0

    for p in preds:
        o = outcomes.get(p["id"])
        state = o["verdict"].upper() if o else "OPEN"
        print(f"[{state:<7}] {p['id']}  ({p['date']})")
        print(f"           {p['claim']}")
        print(f"           check: {p['check']}")
        if o and o.get("evidence"):
            print(f"           outcome: {o['evidence']}")

    tally = {v: sum(1 for o in outcomes.values() if o["verdict"] == v) for v in VERDICTS}
    print(f"\n{len(openp)} open · " + " · ".join(f"{v} {tally[v]}" for v in VERDICTS))
    if tally["wrong"] == 0 and outcomes:
        # Not an error — but worth saying out loud, because a ledger that never records a
        # miss is far more likely to be measuring nothing than to be describing perfection.
        print("\nNothing has been recorded wrong yet. Either the predictions are too safe "
              "to be informative, or the verification is too generous.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="repository path (default: cwd)")
    ap.add_argument("--store", default=DEFAULT_STORE,
                    help=f"ledger path relative to --repo (default: {DEFAULT_STORE})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="record a prediction before the change lands")
    r.add_argument("id", help="stable id, e.g. the branch name or a short slug")
    r.add_argument("--claim", required=True, help="what this change is expected to do")
    r.add_argument("--check", required=True,
                   help="the command or observation that would settle it")
    r.add_argument("--date", required=True, help="ISO date (passed in, never guessed)")

    v = sub.add_parser("verify", help="record the outcome against the original claim")
    v.add_argument("id")
    v.add_argument("--verdict", required=True, choices=VERDICTS)
    v.add_argument("--evidence", help="what the check actually showed")
    v.add_argument("--date", required=True, help="ISO date (passed in, never guessed)")

    ls = sub.add_parser("list", help="show predictions and their outcomes")
    ls.add_argument("--json", action="store_true")

    a = ap.parse_args(argv)
    repo = Path(a.repo)
    if not repo.is_dir():
        print(f"cannot determine: {repo} is not a directory", file=sys.stderr)
        return 2
    store = repo / a.store

    return {"record": cmd_record, "verify": cmd_verify, "list": cmd_list}[a.cmd](a, store)


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
