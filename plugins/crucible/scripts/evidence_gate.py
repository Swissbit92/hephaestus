#!/usr/bin/env python3
"""Report what a repository accepts as proof that a change works.

`finish-branch` used to gate on one sentence: tests green, no regression against the
branch point. In a repository with a test suite that is exactly right. In one without, the
sentence has no referent and the gate quietly becomes a no-op — it reports success because
nothing failed, which is not the same claim.

That is not an edge case. A Unity game, a notebook pipeline, an infrastructure repo and a
design system all verify by *observation*: someone watched it run, an artefact appeared on
disk, an image was captured on the peer that was supposed to see it. The requirement is not
weaker than a test suite, it is differently shaped, and hardcoding one shape hides the
other.

So a repository declares its own evidence classes in `.crucible/evidence.json`, and this
script reports them — optionally narrowed to the classes a given diff actually triggers.

**It reports; it never judges.** Whether the evidence was produced is a human or agent
call. A script that tried to decide it would have to accept a claim as proof, which is the
failure this exists to prevent.

Resolution order:
    1. `.crucible/evidence.json` — an explicit declaration wins.
    2. No declaration, but `detect_profile` finds runnable gates — the implied class is
       "the repo's own test gates pass". This is what keeps existing repos working
       unchanged.
    3. Neither — nothing to gate.

Exit codes:
    0 - an evidence contract exists; the classes are printed
    2 - could not determine (unreadable path, malformed declaration). NOT a pass.
    3 - no declaration and no runnable gates: nothing to gate. A SKIP, NOT a pass, and
        never evidence that a change is safe.
    1 - unused. There is no "regression" for a reporter; kept free so the code never reads
        as one by analogy with the sibling Phase-4.0 scripts.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DECLARATION = Path(".crucible") / "evidence.json"

# The verdict vocabulary. Three values, not two: a check that could not run must never be
# recorded as one that passed. This is the repo-level invariant applied to the gate itself,
# and it is why `finish-branch` writes a verdict word rather than a green tick.
VERDICTS = ("pass", "fail", "could-not-check")

IMPLIED_CLASS = {
    "when": "any change",
    "evidence": "the repository's own test gates pass, with no regression against the "
                "branch point",
    "source": "implied — no .crucible/evidence.json, but runnable test gates were found",
}


def _utf8_stdio() -> None:
    """Force UTF-8 on the streams this script writes to.

    A Windows console defaults to a legacy codepage, so a single arrow in otherwise
    successful output raises UnicodeEncodeError *after* the work is done, turning a passing
    gate into exit 1. No-op where the streams are already UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # detached or captured (pytest); nothing to reconfigure


class Malformed(Exception):
    """The declaration exists but cannot be trusted. Distinct from 'absent' on purpose."""


def load_declaration(repo: Path) -> Optional[Dict[str, Any]]:
    """Parse `.crucible/evidence.json`, or None when there is none.

    Raises Malformed rather than returning a default: a declaration that is present and
    wrong is the one case where guessing is worst — the repo has an opinion and we would
    be overriding it with a weaker one while reporting success.
    """
    path = repo / DECLARATION
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise Malformed("cannot read {}: {}".format(path.as_posix(), exc))
    except json.JSONDecodeError as exc:
        raise Malformed("{} is not valid JSON: {}".format(path.as_posix(), exc))

    if not isinstance(raw, dict):
        raise Malformed("{}: top level must be an object".format(path.as_posix()))
    classes = raw.get("classes")
    if not isinstance(classes, list) or not classes:
        raise Malformed("{}: 'classes' must be a non-empty list".format(path.as_posix()))

    for index, entry in enumerate(classes):
        where = "{}: classes[{}]".format(path.as_posix(), index)
        if not isinstance(entry, dict):
            raise Malformed("{} must be an object".format(where))
        for field in ("when", "evidence"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                raise Malformed("{} needs a non-empty '{}'".format(where, field))
        paths = entry.get("paths")
        if paths is not None and (not isinstance(paths, list)
                                  or not all(isinstance(p, str) for p in paths)):
            raise Malformed("{}: 'paths' must be a list of glob strings".format(where))
    return raw


def has_runnable_gates(repo: Path) -> bool:
    """Whether `detect_profile` reports at least one runnable gate for this repo.

    Invoked as a subprocess rather than imported: it is a sibling script with its own
    exit-code contract, and shelling out keeps that contract the interface. Any failure to
    run it is treated as "no gates found" — this function answers a yes/no question, and
    the caller distinguishes absence from error through the declaration path.
    """
    detector = Path(__file__).resolve().parent / "detect_profile.py"
    if not detector.is_file():
        return False
    try:
        proc = subprocess.run(
            [sys.executable, str(detector), "--repo", str(repo), "--emit-gates"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and bool(proc.stdout.strip())


def changed_files(repo: Path, base: Optional[str]) -> List[str]:
    """Files changed against `base` (or the working tree when base is None)."""
    args = ["git", "-C", str(repo), "diff", "--name-only"]
    if base:
        args.append("{}...HEAD".format(base))
    try:
        proc = subprocess.run(args, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def applies(entry: Dict[str, Any], files: List[str]) -> bool:
    """Whether a class is triggered by these files.

    A class with no `paths` always applies — the safe direction. Narrowing is opt-in, so a
    declaration that forgets to scope a class demands more evidence rather than less.
    """
    patterns = entry.get("paths")
    if not patterns:
        return True
    for name in files:
        for pattern in patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
    return False


def resolve(repo: Path) -> Tuple[List[Dict[str, Any]], str]:
    """The evidence classes for this repo, and where they came from."""
    declared = load_declaration(repo)
    if declared is not None:
        return list(declared["classes"]), "declared"
    if has_runnable_gates(repo):
        return [dict(IMPLIED_CLASS)], "implied"
    return [], "none"


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="repository root")
    parser.add_argument("--base", default=None,
                        help="narrow to classes triggered by the diff against this ref")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="machine-readable output")
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print("not a directory: {}".format(repo.as_posix()), file=sys.stderr)
        return 2

    try:
        classes, source = resolve(repo)
    except Malformed as exc:
        print(str(exc), file=sys.stderr)
        print("a declaration that cannot be parsed is not the same as no declaration; "
              "fix it rather than deleting it", file=sys.stderr)
        return 2

    files: List[str] = []
    if args.base is not None:
        files = changed_files(repo, args.base)
        classes = [c for c in classes if applies(c, files)]

    if source == "none":
        message = ("no .crucible/evidence.json and no runnable test gates: there is "
                   "nothing to gate on here")
        if args.as_json:
            print(json.dumps({"source": source, "classes": [], "verdicts": list(VERDICTS),
                              "message": message}, indent=2))
        else:
            print(message, file=sys.stderr)
            print("declare what counts as proof in .crucible/evidence.json, or add a test "
                  "suite; 'nothing failed' is not the same claim as 'it works'",
                  file=sys.stderr)
        return 3

    if args.as_json:
        print(json.dumps({"source": source, "classes": classes,
                          "verdicts": list(VERDICTS),
                          "changed_files": files}, indent=2))
        return 0

    print("evidence contract: {} ({} class(es))".format(source, len(classes)))
    if args.base is not None:
        print("narrowed to the diff against {} ({} file(s) changed)".format(
            args.base, len(files)))
    for entry in classes:
        print()
        print("  when:     {}".format(entry["when"]))
        print("  evidence: {}".format(entry["evidence"]))
        if entry.get("paths"):
            print("  paths:    {}".format(", ".join(entry["paths"])))
    print()
    print("record one of: {} — 'could-not-check' is a real outcome and must never be "
          "written as 'pass'".format(" | ".join(VERDICTS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
