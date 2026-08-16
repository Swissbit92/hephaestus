#!/usr/bin/env python3
"""Check that every shipped Python file parses on the declared minimum interpreter.

The repository promises a floor (README: "Python 3.9+"). Nothing enforced it, and the
promise was broken: `site.py` used a backslash inside an f-string expression — legal only
from 3.12 under PEP 701 — so on 3.9, 3.10 and 3.11 the *entire test suite failed to
collect*. CI never saw it because all three jobs pinned a single interpreter (3.12); the
matrix varied the OS and not the Python.

Two checks, because one cannot cover the other:

  AST-level    `ast.parse(feature_version=...)` rejects grammar added after the floor
               (`match`, `except*`, parenthesised context managers). Runs anywhere.

  Lexer-level  PEP 701 rewrote the f-string *tokenizer*. `feature_version` does not
               downgrade the tokenizer, so a 3.13 interpreter parses the new syntax
               happily whatever floor is requested — the check that looks like it would
               catch this is exactly the one that cannot. So the constructs are matched
               structurally instead, against the source segment of each f-string
               expression.

Ground truth remains a real interpreter, which is CI's matrix job. This script is what
makes the failure visible on a developer machine that only has a new Python.

Exit codes:
    0 - every file parses at the floor
    1 - at least one file would not
    2 - could not determine (unreadable path, floor unparseable). NOT a pass.
"""
from __future__ import annotations

import argparse
import ast
import io
import sys
import token
import tokenize
from pathlib import Path
from typing import List, Optional, Tuple

PRUNE = {".git", ".venv", "venv", "__pycache__", "node_modules", ".tox",
         "dist", "build", ".mypy_cache", ".pytest_cache", "site-packages"}

# The single source of truth for the promise. `tests/test_python_floor.py` asserts the
# README still states this same value, so prose and enforcement cannot drift apart.
DECLARED_FLOOR = (3, 9)

# Stdlib modules and the version that introduced them. A module-level import of one of
# these is as fatal as a syntax error and just as invisible on a new interpreter: `site.py`
# imported `tomllib` (3.11) at the top, so on 3.9 and 3.10 the module raised
# ModuleNotFoundError and took the whole cms test module down with it at collection.
# Only additions at or above the floor need listing; older ones can never fail.
STDLIB_SINCE = {
    "tomllib": (3, 11),
    "wsgiref.types": (3, 11),
    "graphlib": (3, 9),
    "zoneinfo": (3, 9),
}

# PEP 701 (Python 3.12) lifted three restrictions on f-strings at once. Before it, each
# of these is a SyntaxError, and each is easy to write by accident on a new interpreter.
FSTRING_RULES = (
    ("backslash in an f-string expression",
     "bind the value to a name before the f-string"),
    ("f-string expression reuses the literal's own quote character",
     "use the other quote style inside the expression"),
    ("f-string expression spans multiple lines",
     "compute it on its own line first"),
)


def _utf8_stdio() -> None:
    """Force UTF-8 on the streams this script writes to.

    A Windows console defaults to a legacy codepage, where a single arrow in otherwise
    successful output raises UnicodeEncodeError *after* the work is done — turning a
    passing gate into exit 1. No-op where the streams are already UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # detached or captured (pytest); nothing to reconfigure


def iter_python_files(root: Path) -> List[Path]:
    """Every tracked-looking .py under root, pruned of virtualenvs and caches."""
    out = []
    for path in sorted(root.rglob("*.py")):
        if any(part in PRUNE for part in path.parts):
            continue
        out.append(path)
    return out


def _delimiter(fstring_start: str) -> str:
    """The quote delimiter of an f-string, from its FSTRING_START token (e.g. `rf'''`)."""
    for quote in ('"""', "'''"):
        if fstring_start.endswith(quote):
            return quote
    return fstring_start[-1]


def fstring_findings(src: str) -> List[Tuple[int, str, str]]:
    """Pre-3.12 f-string violations, as (line, what, fix).

    Driven by `tokenize` rather than by the AST. Adjacent string literals are merged into
    a single `JoinedStr`, so the AST cannot say which fragment an expression sits in — and
    the delimiter is exactly the thing the quote-reuse rule needs. `FSTRING_START` gives
    it per fragment, unmerged.

    The tokens only exist from 3.12. That is not a gap: on an older interpreter these
    constructs are a SyntaxError, which `check_file` already reports as the stronger
    signal. This pass exists so a developer on a *new* Python still sees them.
    """
    found = []
    start_type = getattr(token, "FSTRING_START", None)
    if start_type is None:
        return found  # <3.12 — the parser itself is the check

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return found  # unparseable here; check_file owns that verdict

    stack: List[Tuple[str, int]] = []  # (delimiter, opening line)
    for tok in tokens:
        if tok.type == start_type:
            stack.append((_delimiter(tok.string), tok.start[0]))
            continue
        if tok.type == token.FSTRING_END:
            if stack:
                delimiter, opened = stack.pop()
                if len(delimiter) == 1 and tok.end[0] != opened:
                    found.append((opened,) + FSTRING_RULES[2])
            continue
        if not stack or tok.type == token.FSTRING_MIDDLE:
            continue

        # Inside an f-string and not literal text: this token is expression territory.
        delimiter = stack[-1][0]
        if "\\" in tok.string:
            found.append((tok.start[0],) + FSTRING_RULES[0])
        if tok.type == token.STRING and len(delimiter) == 1 and delimiter in tok.string:
            found.append((tok.start[0],) + FSTRING_RULES[1])
    return found


def stdlib_findings(tree: ast.Module, floor: Tuple[int, int]) -> List[Tuple[int, str, str]]:
    """Unguarded module-level imports of stdlib newer than the floor.

    Only *top-level* imports count, and only outside a `try`. An import inside a function
    or behind `try/except ModuleNotFoundError` is a deliberate, working degrade — flagging
    it would punish the correct fix and teach people to switch the check off.
    """
    found = []
    for node in tree.body:  # module scope only; a Try or a def is not walked into
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names = [node.module]
        for name in names:
            since = STDLIB_SINCE.get(name)
            if since and since > floor:
                found.append((
                    node.lineno,
                    "module-level import of {} (stdlib since {}.{})".format(name, *since),
                    "import it inside the function that needs it, "
                    "behind try/except ModuleNotFoundError",
                ))
    return found


def check_file(path: Path, floor: Tuple[int, int]) -> List[str]:
    """Reasons this file would not load on the floor interpreter. Empty means fine."""
    try:
        src = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RuntimeError("cannot read {}: {}".format(path.as_posix(), exc))

    problems = []
    try:
        tree = ast.parse(src, filename=str(path), feature_version=floor)
    except SyntaxError as exc:
        # Grammar newer than the floor, or the file is broken on this interpreter too.
        problems.append("line {}: {}".format(exc.lineno or 0, exc.msg))
        return problems  # no usable parse; the later passes cannot add anything

    for line, what, fix in stdlib_findings(tree, floor):
        problems.append("line {}: {} - {}".format(line, what, fix))

    for line, what, fix in fstring_findings(src):
        problems.append("line {}: {} (pre-3.12 SyntaxError) - {}".format(line, what, fix))
    return problems


def parse_floor(text: str) -> Tuple[int, int]:
    major, _, minor = text.partition(".")
    return (int(major), int(minor))


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="repository root to scan")
    parser.add_argument("--floor", default="{}.{}".format(*DECLARED_FLOOR),
                        help="minimum Python, e.g. 3.9")
    args = parser.parse_args(argv)

    try:
        floor = parse_floor(args.floor)
    except ValueError:
        print("could not parse --floor {!r}; expected e.g. 3.9".format(args.floor),
              file=sys.stderr)
        return 2

    root = Path(args.repo).resolve()
    if not root.is_dir():
        print("not a directory: {}".format(root.as_posix()), file=sys.stderr)
        return 2

    files = iter_python_files(root)
    if not files:
        print("no Python files under {}".format(root.as_posix()), file=sys.stderr)
        return 2

    failures = 0
    for path in files:
        try:
            problems = check_file(path, floor)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if problems:
            failures += 1
            rel = path.relative_to(root).as_posix()
            for problem in problems:
                print("FAIL {}: {}".format(rel, problem))

    print("python floor {}.{}: {} file(s) scanned, {} failing".format(
        floor[0], floor[1], len(files), failures))
    if failures:
        print("a file that does not parse at the floor breaks collection for the whole "
              "suite, not just itself", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
