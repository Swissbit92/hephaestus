#!/usr/bin/env python3
"""Phase 4.0 in one call: every deterministic gate, each once, with one verdict.

develop's QA round used to be a sequence of instructions — run what detect_profile emits,
run coverage_delta (again), run the revert probe, run the invariants — and then the
gatekeeper re-derived the branch-point test set and re-ran the full suite. Measured on a
fixture: 7 test collections and 5 pytest sessions per round, 2 of them full suites, plus
five tool calls whose output all landed in the conversation. This runs each gate exactly
once, prints a compact failures-first summary, and writes the verdict to a file keyed by
the working tree's content, so the gatekeeper reads it instead of re-running anything.

Lanes. Gates that only read the tree (duplicate code, lint, typecheck) run concurrently.
Gates that EXECUTE the project's tests (the suite, collection, the probes, invariant
checks) run one after another by default: this is a generic plugin, and a suite that
binds a fixed port or shares a temp file goes flaky when two copies run at once — and a
flaky REJECT spends a fix round. A repo whose suite is parallel-safe can declare it in
`.crucible/qa.json` as {"parallel_tests": true}; a malformed declaration exits 2.

Each gate is still its own script with its own exit codes; this only schedules them and
aggregates. Aggregate: any 1 → 1 (2s are still listed) · else any 2 → 2 · all 3 → 3 ·
else 0. A could-not-determine never folds into a pass.

Usage:
  qa_gates.py [--repo .] [--final] [--json] [--no-cache]
      --final   also plant defects (mutation_probe --mutate) — the milestone's last round
  qa_gates.py --show      print the verdict for the CURRENT tree; exit 2 if none is current

Exit codes: 0 pass · 1 a gate failed · 2 could not determine · 3 nothing to gate (SKIP).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crucible_common import git_common_dir, git_out, python_exe, run, run_bounded, utf8_stdio  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent
TAIL_LINES = 15
GATE_TIMEOUT = 1800
# A gate is in the static lane only if it is known not to run the project's code. Anything
# unrecognised defaults to the serial lane — the safe side of being wrong.
STATIC = re.compile(r"metric_delta\.py|ruff (check|format)|\bmypy\b|\btsc\b|\beslint\b|npm run lint")


GENERATED = re.compile(r"(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache)/|\.py[co]$")


class Undetermined(Exception):
    pass


# --------------------------------------------------------------------------- the tree key
def tree_key(repo: Path) -> str:
    """Content of the working tree as git sees it: HEAD, the uncommitted diff, and every
    untracked file. Two rounds on the same content share a verdict; any edit misses it."""
    head = git_out(repo, "rev-parse", "HEAD") or "no-head"
    rc, diff = run(["git", "diff", "HEAD", "--binary", "--no-color"], repo)
    if rc != 0:
        raise Undetermined("cannot determine the tree: git diff failed")
    h = hashlib.sha256(head.encode())
    h.update(diff.encode("utf-8", "replace"))
    untracked = git_out(repo, "ls-files", "-o", "--exclude-standard", "-z") or ""
    # Running the gates writes bytecode and tool caches; in a repo without a .gitignore
    # those are untracked files, and counting them would make every verdict stale the
    # moment it was written. They are generated, not edits.
    for rel in sorted(p for p in untracked.split("\x00") if p and not GENERATED.search(p)):
        h.update(rel.encode())
        try:
            h.update((repo / rel).read_bytes())
        except OSError:
            h.update(b"?")
    return h.hexdigest()[:24]


def verdict_path(repo: Path, key: str) -> Path:
    root = git_common_dir(repo)
    if root is None:
        raise Undetermined(f"cannot determine: {repo} is not a git repository")
    return root / "crucible" / "qa" / f"{key}.json"


# --------------------------------------------------------------------------- gates
def declared_parallel(repo: Path) -> bool:
    path = repo / ".crucible" / "qa.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise Undetermined(f"cannot determine: {path.as_posix()} is not valid JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("parallel_tests", False), bool):
        raise Undetermined(f"cannot determine: {path.as_posix()} must be an object whose "
                           "parallel_tests is true or false")
    return data.get("parallel_tests", False)


def plan(repo: Path, final: bool) -> list[dict]:
    py = f'"{Path(python_exe()).as_posix()}"'
    # stdout only: gate lines go there, notes and capabilities go to stderr by contract
    try:
        p = subprocess.run([python_exe(), str(SCRIPTS / "detect_profile.py"), "--repo",
                            str(repo), "--emit-gates"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Undetermined(f"cannot determine the gates: detect_profile did not run ({e})") from None
    if p.returncode not in (0, 3):
        raise Undetermined(f"cannot determine the gates: detect_profile exited {p.returncode}")
    gates = [ln.strip() for ln in p.stdout.splitlines() if ln.strip()] if p.returncode == 0 else []
    has_python_tests = any("pytest" in g for g in gates)
    if has_python_tests:
        gates.append(f'{py} "{(SCRIPTS / "mutation_probe.py").as_posix()}" --revert --repo .')
        if final:
            gates.append(f'{py} "{(SCRIPTS / "mutation_probe.py").as_posix()}" --mutate --repo .')
    if (repo / "docs" / "INVARIANTS.md").exists():
        gates.append(f'{py} "{(SCRIPTS / "invariants_run.py").as_posix()}" --repo .')
    return [{"name": _name(g), "cmd": g, "lane": "static" if STATIC.search(g) else "serial"}
            for g in gates]


_NAMES = (("coverage_delta.py", "coverage-delta"), ("--metric clones", "clones"),
          ("--metric ruff", "lint-delta"), ("--revert", "revert-probe"),
          ("--mutate", "mutation-probe"), ("invariants_run.py", "invariants"),
          ("-m pytest", "tests"), ("ruff format", "format"), ("mypy", "typecheck"))


def _name(cmd: str) -> str:
    for needle, name in _NAMES:
        if needle in cmd:
            return name
    words = cmd.split("&&")[-1].split()
    return words[0] if words else cmd


def run_gate(repo: Path, gate: dict) -> dict:
    started = time.monotonic()
    try:
        b = run_bounded(gate["cmd"], repo, GATE_TIMEOUT, shell=True)
        code, out = b.returncode, b.stdout + b.stderr
        if b.killed:      # the whole tree was stopped; nothing was measured
            code = 2
    except OSError as e:
        code, out = 2, f"could not start: {e}"
    if code == 1 and "Traceback (most recent call last)" in out:
        # a gate that CRASHED exits 1 too — but it measured nothing, so it must not read as
        # a finding ("new duplicates", "a violation"): could not determine, and say so
        code, out = 2, out + "\n(the gate crashed — this is could-not-determine, not a finding)"
    if code not in (0, 1, 2, 3):
        # a tool's own non-scheme code (pytest 4/5, a crash): a failure, not a skip — but
        # pytest's "nothing collected/usage" are could-not-determine, not evidence
        code = 2 if gate["name"] == "tests" and code in (4, 5) else 1
    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-TAIL_LINES:]
    return {**gate, "exit": code, "seconds": round(time.monotonic() - started, 1), "tail": tail}


def aggregate(results: list[dict]) -> int:
    codes = [r["exit"] for r in results]
    if not codes:
        return 3
    if 1 in codes:
        return 1
    if 2 in codes:
        return 2
    if all(c == 3 for c in codes):
        return 3
    return 0


WORD = {0: "PASS", 1: "FAIL", 2: "UNDETERMINED", 3: "SKIP"}


def render(results: list[dict], code: int, cached_note: str = "") -> str:
    lines = [f"{r['name']}: exit {r['exit']} ({r['seconds']}s)" for r in results]
    for r in results:
        if r["exit"] in (1, 2):
            lines.append(f"\n--- {r['name']} (exit {r['exit']}) ---")
            lines += r["tail"]
    lines.append(f"\nQA-GATES: {WORD[code]}{cached_note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    try:
        key = tree_key(repo)
        vpath = verdict_path(repo, key)
        if a.show:
            if not vpath.exists():
                raise Undetermined("no QA verdict for the current tree — run qa_gates.py")
            data = json.loads(vpath.read_text(encoding="utf-8"))
            print(json.dumps(data, indent=2) if a.json else
                  render(data["gates"], data["exit"], f" (current tree, {data['mode']})"))
            return data["exit"]
        gates = plan(repo, a.final)
        if not gates:
            print("no gates for this repository — nothing was checked.\n"
                  "This is a SKIP, not a pass.", file=sys.stderr)
            return 3
        parallel_tests = declared_parallel(repo)
        if a.no_cache:
            os.environ["CRUCIBLE_NO_CACHE"] = "1"
        static = [g for g in gates if g["lane"] == "static"]
        serial = [g for g in gates if g["lane"] == "serial"]
        results: dict[str, dict] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(gates))) as pool:
            futures = {pool.submit(run_gate, repo, g): g["cmd"] for g in static}
            if parallel_tests:
                futures.update({pool.submit(run_gate, repo, g): g["cmd"] for g in serial})
            else:
                for g in serial:          # the test lane: one at a time, alongside statics
                    results[g["cmd"]] = run_gate(repo, g)
            for f in concurrent.futures.as_completed(futures):
                results[futures[f]] = f.result()
        ordered = [results[g["cmd"]] for g in gates]
        code = aggregate(ordered)
        record = {"tree": key, "mode": "final" if a.final else "milestone", "exit": code,
                  "verdict": WORD[code], "gates": ordered,
                  "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        vpath.parent.mkdir(parents=True, exist_ok=True)
        tmp = vpath.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
        os.replace(tmp, vpath)
    except Undetermined as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(record, indent=2) if a.json else render(ordered, code))
    return code


if __name__ == "__main__":
    utf8_stdio()
    raise SystemExit(main())
