#!/usr/bin/env python3
"""Do the tests actually notice when the change is wrong? Two probes, Python only.

A green suite says the tests agree with the code, not that they would disagree with a
broken version of it. LLM-written tests are measurably weak here: on one benchmark the
best model's tests caught about a third of planted defects, and on SWE-bench most tasks
admit a wrong patch that passes every test. Both probes work in a throwaway COPY of the
repo — the user's working tree is never written — and both refuse to report a result
unless they have first shown that the tests run the copied code at all.

  --revert   "delete the fix": restore the branch point's version of every changed
             non-test file (and drop files the branch added), then run the changed tests.
             They must FAIL — a test that passes without the change does not test it.
             Cheap: one run. Meant for every milestone.
  --mutate   plant up to --max-mutants (default 6) small defects in the functions this
             branch changed (a flipped comparison, swapped arithmetic, and/or, min/max or
             any/all, a constant off by one or a flipped bool, a negated condition,
             `return None`) and run the tests against
             each. A mutant the tests do not kill is a defect they would ship. Costs about
             (mutants + 2) test runs; meant for the final milestone, or on demand.

Canaries, both required before any verdict:
  1. the unmodified copy's tests pass — else the copy itself is broken;
  2. a sentinel that makes the changed module raise on import is caught — else the tests
     are importing some other copy of the code (an editable install, a PYTHONPATH), and
     every mutant would "survive" for that reason alone.

A surviving mutant is a finding to inspect, not an automatic REJECT: some mutants are
equivalent to the original (`x >= 0` vs `x > 0` where x is never 0). Say which, or add the
test that kills it.

Exit codes:
  0 — the tests depend on the change (revert) / every mutant was killed (mutate)
  1 — the tests pass without the change / some mutants survived (listed)
  2 — could not determine: a canary failed, no branch point, the test command did not run.
      NOT a pass.
  3 — nothing to probe: no changed tests (revert), the change only adds code its tests
      import (revert), or no changed Python function (mutate). A SKIP, not a pass.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crucible_common import (  # noqa: E402
    detect_target,
    git_out,
    merge_base,
    python_exe,
    run,
    run_bounded,
    utf8_stdio,
)

DEFAULT_MAX_MUTANTS = 6
TEST_PATH = re.compile(r"(^|/)(tests?/|test_[^/]*\.py$|[^/]*_test\.py$|conftest\.py$)")
GENERATED = re.compile(r"(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache)/|\.py[co]$")
SENTINEL = 'raise RuntimeError("mutation_probe sentinel: the tests imported this copy")\n'


class Undetermined(Exception):
    pass


class Skip(Exception):
    pass


# --------------------------------------------------------------------------- the copy
def branch_point(repo: Path, target: str | None, base: str | None) -> str:
    if base:
        return base
    t = detect_target(repo, target)
    if not t:
        raise Undetermined("cannot determine: no integration branch found; pass --target or --base")
    b = merge_base(repo, t)
    if not b:
        raise Undetermined(f"cannot determine: no merge-base with {t}")
    return b


def changed_paths(repo: Path, base: str) -> list[str]:
    tracked = git_out(repo, "diff", "--name-only", base, "--")
    untracked = git_out(repo, "ls-files", "-o", "--exclude-standard")
    if tracked is None or untracked is None:
        raise Undetermined("cannot determine: git could not list the changed files")
    # bytecode and tool caches are not changes: an earlier gate's test run writes them, and
    # in a repo without a .gitignore they show up as untracked "sources" to revert
    return sorted({p for p in (tracked + "\n" + untracked).splitlines() if p and not GENERATED.search(p)})


def copy_tree(repo: Path, dest: Path) -> None:
    """Copy what git sees (tracked + untracked, minus ignored) — the working tree as the
    user has it, uncommitted edits included, without touching their index or stash."""
    listing = git_out(repo, "ls-files", "-co", "--exclude-standard", "-z")
    if listing is None:
        raise Undetermined("cannot determine: git ls-files failed")
    for rel in listing.split("\x00"):
        src = repo / rel
        if rel and src.is_file():
            (dest / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / rel)


def run_tests(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, float]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    t0 = time.monotonic()
    try:
        # bounded: a mutant that loops (or allocates without end) is stopped with its WHOLE
        # process tree — a plain timeout killed only `uv`/`sh` and orphaned the test runner
        rc = run_bounded(cmd, cwd, timeout, env=env).returncode
    except OSError as e:
        raise Undetermined(f"cannot determine: the test command did not start ({e})") from None
    return rc, time.monotonic() - t0   # -1 = killed (hang/runaway): the tests noticed something


def canaries(cmd: list[str], copy: Path, sources: list[str]) -> float:
    """Both canaries; returns the clean run's duration for the per-mutant timeout."""
    rc, took = run_tests(cmd, copy, timeout=1800)
    if rc != 0:
        raise Undetermined(f"cannot determine: the tests do not pass in an unmodified copy "
                           f"(exit {rc}), so no probe result would mean anything")
    if not sources:
        return took     # nothing importable changed (config, data): no module to plant into
    for rel in sources:
        f = copy / rel
        original = f.read_text(encoding="utf-8")
        f.write_text(SENTINEL + original, encoding="utf-8")
        try:
            rc, _ = run_tests(cmd, copy, timeout=max(60, int(took * 3)))
        finally:
            f.write_text(original, encoding="utf-8")
        if rc != 0:
            return took
    raise Undetermined("cannot determine: the tests still pass when the changed modules raise "
                       "on import — they are running some other copy of the code (an editable "
                       "install? a PYTHONPATH?), so every probe would pass or survive by accident")


# --------------------------------------------------------------------------- mutants
_CMP_SWAP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt,
             ast.Gt: ast.LtE, ast.LtE: ast.Gt}
_BIN_SWAP = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.Div: ast.Mult,
             ast.FloorDiv: ast.Mult}
# Builtins with an obvious wrong twin. A function built from calls rather than operators
# (`min(hi, max(lo, x))`) otherwise offers nothing but `return None` to mutate.
_NAME_SWAP = {"min": "max", "max": "min", "any": "all", "all": "any"}


def _sites(tree: ast.AST, lines: set[int]) -> list[tuple[str, int, int]]:
    """(operator, node line, ordinal) for every mutable node inside a function this branch
    touched. The ordinal re-finds the node in a fresh parse of the same source."""
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and any(n.lineno <= ln <= (n.end_lineno or n.lineno) for ln in lines)]
    out, seen = [], set()
    for fn in funcs:
        for node in ast.walk(fn):
            for op, ok in (("compare", isinstance(node, ast.Compare) and type(node.ops[0]) in _CMP_SWAP),
                           ("arith", isinstance(node, (ast.BinOp, ast.AugAssign)) and type(node.op) in _BIN_SWAP),
                           ("boolop", isinstance(node, ast.BoolOp)),
                           ("negate-if", isinstance(node, (ast.If, ast.While))),
                           ("return-none", isinstance(node, ast.Return) and node.value is not None
                            and not (isinstance(node.value, ast.Constant) and node.value.value is None)),
                           ("constant", isinstance(node, ast.Constant) and type(node.value) in (int, bool)),
                           ("swap-call", isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                            and node.func.id in _NAME_SWAP)):
                if ok and (op, id(node)) not in seen:
                    seen.add((op, id(node)))
                    out.append((op, node.lineno, id(node)))
    # deterministic ordinals by walk order
    order = {nid: i for i, nid in enumerate(id(n) for n in ast.walk(tree))}
    return [(op, line, order[nid]) for op, line, nid in out]


def _apply(source: str, op: str, ordinal: int) -> str:
    tree = ast.parse(source)
    node = list(ast.walk(tree))[ordinal]
    if op == "compare":
        node.ops[0] = _CMP_SWAP[type(node.ops[0])]()
    elif op == "arith":
        node.op = _BIN_SWAP[type(node.op)]()
    elif op == "boolop":
        node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    elif op == "negate-if":
        node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
    elif op == "return-none":
        node.value = ast.Constant(value=None)
    elif op == "constant":
        node.value = (not node.value) if type(node.value) is bool else node.value + 1
    elif op == "swap-call":
        node.func.id = _NAME_SWAP[node.func.id]
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def pick(sites: list[tuple[str, str, int, int]], limit: int) -> list[tuple[str, str, int, int]]:
    """Spread the budget: round-robin over operators so six mutants are not six constants."""
    by_op: dict[str, list] = {}
    for s in sites:
        by_op.setdefault(s[1], []).append(s)
    chosen = []
    while len(chosen) < limit and any(by_op.values()):
        for op in sorted(by_op):
            if by_op[op] and len(chosen) < limit:
                chosen.append(by_op[op].pop(0))
    return chosen


def changed_line_map(repo: Path, base: str, paths: list[str]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for rel in paths:
        diff = git_out(repo, "diff", "-U0", "--no-color", base, "--", rel)
        lines: set[int] = set()
        if diff:
            for m in re.finditer(r"^@@ .*?\+(\d+)(?:,(\d+))?", diff, re.M):
                start, count = int(m.group(1)), int(m.group(2) or 1)
                lines.update(range(start, start + count))
        else:   # untracked or new: the whole file is the change
            try:
                lines = set(range(1, (repo / rel).read_text(encoding="utf-8").count("\n") + 2))
            except OSError:
                pass
        out[rel] = lines
    return out


# --------------------------------------------------------------------------- probes
def probe_revert(repo: Path, base: str, cmd: list[str]) -> tuple[int, str]:
    changed = changed_paths(repo, base)
    tests = [p for p in changed if TEST_PATH.search(p) and p.endswith(".py")]
    sources = [p for p in changed if not TEST_PATH.search(p)]
    if not tests:
        raise Skip("nothing to probe: the branch changed no test, so there is no test to "
                   "show depends on the change")
    if not sources:
        raise Skip("nothing to probe: the branch changed only tests")
    with tempfile.TemporaryDirectory(prefix="mutprobe-") as td:
        copy = Path(td)
        copy_tree(repo, copy)
        py_sources = [p for p in sources if p.endswith(".py") and (copy / p).exists()]
        canaries(cmd + tests, copy, py_sources)
        for rel in sources:
            # raw, not git_out(): stripping would mangle the file being restored
            rc, old = run(["git", "show", f"{base}:{rel}"], repo)
            target = copy / rel
            if rc != 0:                          # added by this branch
                if target.exists():
                    target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(old, encoding="utf-8")
        rc, _ = run_tests(cmd + tests, copy, timeout=1800)
    if rc in (2, 4, 5):
        raise Skip("nothing to revert to: without the change the tests cannot even be "
                   "collected — they exercise code the branch added (additive change)")
    if rc == 0:
        return 1, ("the changed tests PASS with the change reverted — they do not test it:\n"
                   + "".join(f"  - {t}\n" for t in tests))
    return 0, "OK — the changed tests fail without the change: they depend on it."


def probe_mutate(repo: Path, base: str, cmd: list[str], limit: int, mutant_timeout: int = 0) -> tuple[int, str]:
    changed = changed_paths(repo, base)
    sources = [p for p in changed if p.endswith(".py") and not TEST_PATH.search(p)
               and (repo / p).is_file()]
    lines = changed_line_map(repo, base, sources)
    sites = []
    for rel in sources:
        try:
            tree = ast.parse((repo / rel).read_text(encoding="utf-8"))
        except (SyntaxError, OSError):
            continue
        sites += [(rel, op, line, ordinal) for op, line, ordinal in _sites(tree, lines[rel])]
    chosen = pick(sites, limit)
    if not chosen:
        raise Skip("nothing to probe: the branch changed no Python function")
    survivors = []
    with tempfile.TemporaryDirectory(prefix="mutprobe-") as td:
        copy = Path(td)
        copy_tree(repo, copy)
        took = canaries(cmd, copy, sorted({c[0] for c in chosen}))
        for rel, op, line, ordinal in chosen:
            f = copy / rel
            original = f.read_text(encoding="utf-8")
            try:
                f.write_text(_apply(original, op, ordinal), encoding="utf-8")
                rc, _ = run_tests(cmd, copy, timeout=mutant_timeout or max(60, int(took * 3)))
            finally:
                f.write_text(original, encoding="utf-8")
            if rc == 0:
                survivors.append(f"  - {rel}:{line}  {op}")
    if survivors:
        return 1, (f"{len(survivors)}/{len(chosen)} mutants SURVIVED — the tests pass with "
                   "these defects planted. Add the test that kills each, or say why it is "
                   "equivalent to the original:\n" + "\n".join(survivors) + "\n")
    return 0, f"OK — all {len(chosen)} mutants were killed by the tests."


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--revert", action="store_true")
    mode.add_argument("--mutate", action="store_true")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--target")
    ap.add_argument("--base")
    ap.add_argument("--test-cmd", help="test command (default: this interpreter's pytest)")
    ap.add_argument("--max-mutants", type=int, default=DEFAULT_MAX_MUTANTS)
    ap.add_argument("--mutant-timeout", type=int, default=0,
                    help="seconds per mutant run (default: 3x the clean run, at least 60)")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    cmd = a.test_cmd.split() if a.test_cmd else [python_exe(), "-m", "pytest", "-q", "-x",
                                                 "-p", "no:cacheprovider"]
    try:
        if not (a.revert or a.mutate):
            raise Undetermined("cannot determine: pass --revert or --mutate")
        if git_out(repo, "rev-parse", "--git-dir") is None:
            raise Undetermined(f"cannot determine: {repo} is not a git repository")
        base = branch_point(repo, a.target, a.base)
        code, msg = probe_revert(repo, base, cmd) if a.revert else \
            probe_mutate(repo, base, cmd, max(1, a.max_mutants), a.mutant_timeout)
    except Undetermined as e:
        print(str(e), file=sys.stderr)
        return 2
    except Skip as e:
        print(f"{e}\nThis is a SKIP, not a pass.", file=sys.stderr)
        return 3
    print(msg, end="" if msg.endswith("\n") else "\n")
    return code


if __name__ == "__main__":
    utf8_stdio()
    raise SystemExit(main())
