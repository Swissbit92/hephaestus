"""Test-log summarizer for loop-harness — pure stdlib.

The deterministic floor of the loop's "log inspection" step: turn raw test output into a
structured summary (counts + failing node IDs + a clean one-line summary) so the loop records
*signal*, not raw progress dots. Pytest-oriented; also recognizes the generic "N passed /
N failed" shape.

Safe default: if no recognizable summary is found, `ok` is False (matched=False) — a sweeper
should never claim "green" from output it couldn't parse.

CLI: python3 loop_logscan.py [--file PATH]   # reads stdin when no --file; prints a JSON summary
"""
from __future__ import annotations

import argparse
import json
import re
import sys

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_COUNT = {
    "passed": re.compile(r"(\d+)\s+passed"),
    "failed": re.compile(r"(\d+)\s+failed"),
    "errors": re.compile(r"(\d+)\s+errors?"),
    "skipped": re.compile(r"(\d+)\s+skipped"),
}
# A pytest failure/error line: `FAILED path::test - reason` or `ERROR path::test`.
_FAILED_NODE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)


def _utf8_stdio() -> None:
    """Force UTF-8 on the streams this script writes to.

    Deliberately local rather than `loop_common.use_utf8_stdio`: importing
    loop_common resolves and *creates* the state directory at import time, and
    this script has no state — a log parser should not make a directory as a side
    effect of being imported. Duplicating six lines is the cheaper trade.

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


def _clean_summary_line(text: str) -> str:
    candidates = [l.strip() for l in text.splitlines() if any(p.search(l) for p in _COUNT.values())]
    return candidates[-1] if candidates else ""


def summarize(text: str) -> dict:
    """Parse test output into {ok, matched, passed, failed, errors, skipped, failing_tests, summary}."""
    text = _ANSI.sub("", text)
    counts = {k: (int(m.group(1)) if (m := p.search(text)) else 0) for k, p in _COUNT.items()}
    matched = any(p.search(text) for p in _COUNT.values())
    failing = sorted(set(_FAILED_NODE.findall(text)))
    ok = matched and counts["failed"] == 0 and counts["errors"] == 0
    return {
        "ok": ok,
        "matched": matched,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "errors": counts["errors"],
        "skipped": counts["skipped"],
        "failing_tests": failing,
        "summary": _clean_summary_line(text),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="loop_logscan", description="summarize test output for a loop")
    parser.add_argument("--file", default=None, help="read this file instead of stdin")
    args = parser.parse_args(argv)
    text = open(args.file, encoding="utf-8").read() if args.file else sys.stdin.read()
    print(json.dumps(summarize(text)))
    return 0


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
