#!/usr/bin/env python3
"""No shipped plugin script may decide anything durable from a file's mtime.

git neither records nor restores modification times. A clone stamps every file with the
checkout time, so any rule computed from `st_mtime` silently reports every document as
brand new the moment the repository moves to another machine — on CI, in a fresh clone,
for every consumer who did not copy the working tree byte-for-byte. This is the standard
answer, not a local opinion: the reproducible-builds specification records the same
constraint and prescribes the same fix — use the last git commit timestamp, because
individual file timestamps cannot survive a checkout.

The reason this is an *invariant* and not a comment is that it has already been learned
here twice and shipped wrong four times. `render.py` hit it first and wrote the lesson
into its own docstring, where it stayed: the archive rule then made the identical mistake
at four separate sites (`check.py`, `migrate.py` twice, `add_frontmatter.py`), and the
last of those *persisted* a wrong date into frontmatter. A lesson recorded only where it
was learned does not travel. A check does.

Why AST rather than grep: the module that fixed the bug, `doc_age.py`, discusses
`st_mtime` at length in its docstring. A textual search flags it — that is, the rule's
first action would be to accuse its own remedy — and a rule that fires on its own fix is
one people switch off. Attribute access and call syntax are visible to the parser and
prose in a string is not, so the parser is the right instrument.

Exit codes:
    0 — no unapproved mtime read
    1 — an unapproved mtime read (the invariant is violated)
    2 — could not determine (a file would not parse); NOT a pass
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Directories whose Python ships inside a plugin and therefore runs on other people's
# clones. Repo-local tooling (scripts/, tests/, evals/) is deliberately out of scope: it
# runs on a working tree someone already has, where mtime means what it appears to mean.
SHIPPED_GLOBS = (
    "plugins/*/scripts/*.py",
    "plugins/*/skills/*/scripts/*.py",
)

# Files permitted to read mtime, each with the reason it is sound. An entry here is a
# claim that the decision is NOT clone-stable-sensitive, and it has to survive being read
# aloud. Adding one is a deliberate act; that is the point of keeping the list short.
ALLOWED = {
    "plugins/second-brain/skills/second-brain/scripts/vault_graph.py":
        "An Obsidian vault is a working directory a person edits in place, not an artefact "
        "anyone clones. 'How long since I touched this note' is exactly what mtime means "
        "there, and no git checkout stands between the edit and the reading.",
}

MTIME_ATTRS = {"st_mtime", "st_mtime_ns"}
MTIME_FUNCS = {"getmtime"}


def _iter_shipped(repo: Path):
    for pattern in SHIPPED_GLOBS:
        for path in sorted(repo.glob(pattern)):
            if path.name.startswith("_"):
                continue
            yield path


def find_mtime_reads(tree: ast.AST) -> list:
    """(lineno, what) for every syntactic mtime read. Strings are invisible here."""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in MTIME_ATTRS:
            hits.append((node.lineno, f".{node.attr}"))
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name in MTIME_FUNCS:
                hits.append((node.lineno, f"{name}()"))
    return hits


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fail on mtime reads in shipped plugin code")
    ap.add_argument("--repo", default=".", help="repository path (default: cwd)")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()

    violations = []
    undetermined = []
    scanned = 0

    for path in _iter_shipped(repo):
        rel = path.relative_to(repo).as_posix()
        scanned += 1
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=rel)
        except SyntaxError as e:
            undetermined.append(f"{rel}: {e}")
            continue
        hits = find_mtime_reads(tree)
        if not hits or rel in ALLOWED:
            continue
        for lineno, what in hits:
            violations.append(f"{rel}:{lineno}: reads {what}")

    if undetermined:
        for line in undetermined:
            print(f"  could not parse  {line}", file=sys.stderr)
        print(f"\ncould not determine: {len(undetermined)} file(s) did not parse — "
              f"this is not a pass.", file=sys.stderr)
        return 2

    if violations:
        for line in violations:
            print(f"  VIOLATION  {line}", file=sys.stderr)
        print(f"\n{len(violations)} mtime read(s) in shipped plugin code.\n"
              f"\n"
              f"git does not restore mtimes, so this decides on the clone's checkout time\n"
              f"rather than on anything about the file. Use the git committer date -\n"
              f"plugins/crucible/skills/cms/scripts/doc_age.py already does this and is\n"
              f"importable - or a date carried in the file's own content.\n"
              f"\n"
              f"If the decision genuinely is not clone-sensitive, add the file to ALLOWED in\n"
              f"scripts/mtime_guard.py with the reason. The reason is the part that matters:\n"
              f"it is what stops the list becoming a place to put inconvenient findings.",
              file=sys.stderr)
        return 1

    print(f"mtime guard: {scanned} shipped file(s) scanned, "
          f"{len(ALLOWED)} allowlisted, 0 violations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
