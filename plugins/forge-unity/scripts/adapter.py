#!/usr/bin/env python3
"""Resolve a project's own commands behind an engine-neutral vocabulary.

A published plugin cannot ship the commands that matter most. The interesting observation
verbs in a real game — start a session on this peer, drive tick-exact input, dump the
trace, composite N frames into one contact sheet — are implemented *in that game's own
source*, under names only that project uses. A skill naming them directly would work for
exactly one repository on earth.

So the seam inverts. The plugin owns the **vocabulary** and the **detector**; the project
owns the **implementation** and declares the mapping in `.forge/adapter.json`:

    {
      "engine": "unity",
      "transport": {"command": "node tools/bridge.mjs exec {verb} {json}"},
      "verbs": {
        "editor.compile":  "recompile_scripts",
        "session.start":   "mygame_session_start",
        "capture.sheet":   "mygame_capture_sheet"
      }
    }

Two consequences worth stating, because they are the whole design:

- **A workflow is written once.** `finish-branch` can ask for `capture.sheet` without
  knowing any project's naming, and a Godot or Unreal adapter becomes a config file rather
  than a rewrite of every skill.
- **An unimplemented verb is a reported gap, never a guess.** `--resolve` on a verb this
  project does not implement exits 3, which the evidence gate reads as `could-not-check`.
  Inventing a plausible command name is the one failure this must never have: it produces a
  call that looks correct, runs nothing, and is reported as a success.

Exit codes:
    0 - resolved, or the declaration is valid
    2 - could not determine: the file is present and malformed, or a template is unusable.
        Never falls back to a default; a project that has stated its mapping must not be
        overridden by a guess.
    3 - no `.forge/adapter.json`, or the requested verb is not implemented here. A SKIP,
        NOT a pass, and never evidence that anything ran.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

DECLARATION = Path(".forge") / "adapter.json"

# The engine-neutral vocabulary. Grouped by the question each answers, because that is what
# makes the set portable: every engine can be asked these, and none of them names a vendor.
VERBS: Dict[str, str] = {
    # Is the tool alive, and does the code build?
    "editor.ping": "answer whether the editor/runtime is reachable at all",
    "editor.compile": "compile, exiting non-zero on error so it works as a gate",
    "editor.logs": "read the console, de-duplicated and de-noised",
    # Make it run.
    "session.start": "start a run on this peer",
    "session.status": "report whether the run actually started (the start is async)",
    # Drive it reproducibly.
    "input.script": "drive input deterministically, so a run can be repeated against a fix",
    # Find out what it did.
    "trace.dump": "one row per simulated step",
    "trace.transitions": "the cheap view — state changes only",
    "capture.sheet": "N frames composited into one image, each stamped with its step",
}

# Without these, nothing else can be trusted: you cannot gate a change on a run you cannot
# start, nor on a compile you cannot check. Everything else is optional and degrades to
# could-not-check.
REQUIRED = ("editor.compile",)


def _utf8_stdio() -> None:
    """Force UTF-8 on the streams this script writes to.

    A Windows console defaults to a legacy codepage, so a single arrow in otherwise
    successful output raises UnicodeEncodeError after the work is done, turning a passing
    gate into exit 1. No-op where the streams are already UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


class Malformed(Exception):
    """Present but untrustworthy. Deliberately distinct from absent."""


def load(repo: Path) -> Optional[Dict[str, Any]]:
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

    transport = raw.get("transport")
    if not isinstance(transport, dict):
        raise Malformed("{}: 'transport' must be an object".format(path.as_posix()))
    command = transport.get("command")
    if not isinstance(command, str) or not command.strip():
        raise Malformed("{}: transport.command must be a non-empty string".format(
            path.as_posix()))
    if "{verb}" not in command:
        raise Malformed(
            "{}: transport.command must contain {{verb}} — without it every verb would "
            "run the same command, which fails by doing the wrong thing silently".format(
                path.as_posix()))
    try:
        check_template(command)   # validated here so --list catches it, not only --resolve
    except Malformed as exc:
        raise Malformed("{}: {}".format(path.as_posix(), exc))

    verbs = raw.get("verbs")
    if not isinstance(verbs, dict) or not verbs:
        raise Malformed("{}: 'verbs' must be a non-empty object".format(path.as_posix()))
    for name, target in verbs.items():
        if not isinstance(target, str) or not target.strip():
            raise Malformed("{}: verbs[{!r}] must be a non-empty string".format(
                path.as_posix(), name))
    return raw


def unknown_verbs(declared: Dict[str, Any]) -> List[str]:
    """Declared names outside the vocabulary — a typo, or a rename never followed through."""
    return sorted(name for name in declared["verbs"] if name not in VERBS)


def missing_required(declared: Dict[str, Any]) -> List[str]:
    return [name for name in REQUIRED if name not in declared["verbs"]]


PLACEHOLDER = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
KNOWN_PLACEHOLDERS = {"verb", "json"}


def check_template(command: str) -> None:
    """Reject unsupported placeholders — on the template, before anything is substituted.

    Checking the *rendered* string cannot work: the payload is JSON, so it legitimately
    contains braces of its own, and a `{}` argument would be read as an unfilled
    placeholder. The template is the only thing that can be judged.
    """
    unknown = sorted(set(PLACEHOLDER.findall(command)) - KNOWN_PLACEHOLDERS)
    if unknown:
        raise Malformed(
            "transport.command uses unsupported placeholder(s) {}; only {{verb}} and "
            "{{json}} are substituted".format(", ".join("{" + u + "}" for u in unknown)))


def resolve(declared: Dict[str, Any], verb: str, payload: str) -> str:
    """The concrete command line for a verb, with the project's own name substituted."""
    target = declared["verbs"][verb]
    command = declared["transport"]["command"]
    check_template(command)
    return command.replace("{verb}", target).replace("{json}", shlex.quote(payload))


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="project root")
    parser.add_argument("--resolve", metavar="VERB",
                        help="print the command implementing this verb")
    parser.add_argument("--json", default="{}", metavar="PAYLOAD",
                        help="payload substituted for {json} when resolving")
    parser.add_argument("--list", action="store_true",
                        help="show the vocabulary and what this project implements")
    parser.add_argument("--vocabulary", action="store_true",
                        help="print the canonical verbs and exit (needs no project)")
    args = parser.parse_args(argv)

    if args.vocabulary:
        for name, purpose in VERBS.items():
            print("{:20s} {}{}".format(
                name, purpose, "  [required]" if name in REQUIRED else ""))
        return 0

    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print("not a directory: {}".format(repo.as_posix()), file=sys.stderr)
        return 2

    try:
        declared = load(repo)
    except Malformed as exc:
        print(str(exc), file=sys.stderr)
        print("a mapping that cannot be parsed is not the same as no mapping; fix it "
              "rather than deleting it", file=sys.stderr)
        return 2

    if declared is None:
        print("no {} in {}".format(DECLARATION.as_posix(), repo.as_posix()), file=sys.stderr)
        print("run /forge-init to write one; until then no observation verb can be "
              "resolved and every evidence class that needs one is could-not-check",
              file=sys.stderr)
        return 3

    unknown = unknown_verbs(declared)
    missing = missing_required(declared)

    if args.resolve:
        verb = args.resolve
        if verb not in VERBS:
            print("{!r} is not in the vocabulary; --vocabulary lists it".format(verb),
                  file=sys.stderr)
            return 2
        if verb not in declared["verbs"]:
            print("this project does not implement {!r}".format(verb), file=sys.stderr)
            print("that is a gap to report, not a command to invent: a plausible-looking "
                  "guess runs nothing and reports success", file=sys.stderr)
            return 3
        try:
            print(resolve(declared, verb, args.json))
        except Malformed as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0

    engine = declared.get("engine", "unspecified")
    implemented = declared["verbs"]
    print("adapter: engine={} · {}/{} verbs implemented".format(
        engine, len(set(implemented) & set(VERBS)), len(VERBS)))
    if args.list:
        for name, purpose in VERBS.items():
            mark = "->  {}".format(implemented[name]) if name in implemented else "--  (not implemented)"
            print("  {:20s} {}".format(name, mark))
    for name in unknown:
        print("unknown verb {!r} — not in the vocabulary; typo, or a rename never "
              "finished".format(name), file=sys.stderr)
    for name in missing:
        print("required verb {!r} is not implemented".format(name), file=sys.stderr)
    if missing:
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
