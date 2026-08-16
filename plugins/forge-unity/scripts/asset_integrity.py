#!/usr/bin/env python3
"""Find the Unity failures that neither the compiler nor the editor will tell you about.

Unity keeps a second, parallel record of every asset in `.meta` files, and that record is
what the editor believes rather than what is on disk. When the two disagree nothing errors:
a script with no `.meta` is simply *not imported*, so it does not compile, does not appear
in menus, and cannot be attached — while looking completely normal in a file listing and in
git. A `.meta` whose asset was deleted outside the editor lingers as a reference to nothing.
A component whose script reference broke serialises as `m_Script: {fileID: 0}` and silently
does nothing at runtime.

Each of these is invisible to a build, invisible to a test, and invisible in review. That is
the entire justification for this script existing: it checks the bookkeeping, which is the
one Unity-specific thing that has not changed across engine versions and is not already
covered by ten published reference packs.

**It reports; it never repairs.** Editing a `.meta` by hand is how a GUID gets duplicated
across two assets, which breaks every reference to both and cannot be undone by editing it
back. Repair goes through the editor or the importer API. The unwired check in particular
cannot distinguish dead code from a feature mid-construction, so it is reported as a
question.

Exit codes:
    0 - no integrity problems found
    1 - at least one problem found
    2 - could not determine (no source root, unreadable tree). NOT a pass.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# Unity's own folders and anything vendored. A vendored SDK's bookkeeping is its author's
# problem, and reporting it drowns the findings that belong to this project.
PRUNE = {"Library", "Temp", "obj", "Logs", "Build", "Builds", "UserSettings",
         "node_modules", ".git", ".vs", ".idea"}

SOURCE_SUFFIXES = {".cs"}
SCENE_SUFFIXES = {".prefab", ".unity", ".asset", ".controller", ".mat"}

GUID = re.compile(r"^guid:\s*([0-9a-fA-F]{32})\s*$", re.M)
BROKEN_SCRIPT = re.compile(r"m_Script:\s*\{fileID:\s*0\b")

# Only a type Unity can actually attach to something can be *unwired*. An interface, enum,
# struct or static helper is referenced from code and never from a scene, so asking whether
# it appears in a prefab is a category error — and one that buries the real findings: on a
# real project this filter cut 29 "unwired" reports to the handful that could be wired.
ATTACHABLE = re.compile(
    r"^\s*(?:public|internal|sealed|abstract|partial|\s)*class\s+\w+\s*:\s*[^{\n]*\b"
    r"(?:MonoBehaviour|NetworkBehaviour|ScriptableObject|StateMachineBehaviour)\b",
    re.M)


def _utf8_stdio() -> None:
    """Force UTF-8 on the streams this script writes to.

    A Windows console defaults to a legacy codepage, so a single arrow in otherwise
    successful output raises UnicodeEncodeError after the work is done, turning a passing
    gate into exit 1. Unity projects are frequently on Windows, so this is not theoretical.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _walk(root: Path) -> List[Path]:
    out = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in PRUNE for part in path.relative_to(root).parts):
            continue
        out.append(path)
    return out


def _read(path: Path) -> str:
    """Text of a file, tolerant of the mixed encodings a Unity tree accumulates."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def find_source_without_meta(files: List[Path], root: Path) -> List[str]:
    """Source Unity never imported: no `.meta`, so it does not compile and cannot attach."""
    known = {f.as_posix() for f in files}
    out = []
    for path in files:
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        if path.with_suffix(path.suffix + ".meta").as_posix() not in known:
            out.append(path.relative_to(root).as_posix())
    return out


def find_orphan_meta(files: List[Path], root: Path) -> List[str]:
    """A `.meta` whose asset is gone — a delete that happened outside the editor."""
    known = {f.as_posix() for f in files}
    out = []
    for path in files:
        if path.suffix.lower() != ".meta":
            continue
        asset = path.with_suffix("")  # strip only the .meta layer
        if asset.as_posix() in known:
            continue
        # A folder .meta is legitimate when the folder still exists.
        if asset.is_dir():
            continue
        out.append(path.relative_to(root).as_posix())
    return out


def find_broken_script_refs(files: List[Path], root: Path) -> List[str]:
    """`m_Script: {fileID: 0}` — a component pointing at a script that no longer resolves."""
    out = []
    for path in files:
        if path.suffix.lower() not in SCENE_SUFFIXES:
            continue
        if BROKEN_SCRIPT.search(_read(path)):
            out.append(path.relative_to(root).as_posix())
    return out


def find_unwired(files: List[Path], root: Path) -> List[str]:
    """Behaviours whose GUID appears in no scene, prefab or asset.

    Reported as a question, never as a defect. During a migration or a half-built feature an
    unwired behaviour is expected; the probe cannot tell that from dead code, and pretending
    otherwise is how a real feature gets deleted.
    """
    referenced: Set[str] = set()
    for path in files:
        if path.suffix.lower() in SCENE_SUFFIXES:
            for match in re.finditer(r"guid:\s*([0-9a-fA-F]{32})", _read(path)):
                referenced.add(match.group(1).lower())

    out = []
    for path in files:
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        parts = path.relative_to(root).parts
        if "Editor" in parts:
            continue  # editor tooling is invoked from menus, never wired to an object
        if not ATTACHABLE.search(_read(path)):
            continue  # an interface or enum cannot be wired, so it cannot be unwired
        meta = path.with_suffix(path.suffix + ".meta")
        if not meta.is_file():
            continue  # already reported by the no-meta check; do not double-count
        found = GUID.search(_read(meta))
        if not found:
            continue
        if found.group(1).lower() not in referenced:
            out.append(path.relative_to(root).as_posix())
    return out


CHECKS: Tuple[Tuple[str, str, str], ...] = (
    ("no-meta", "source Unity never imported (no .meta: not compiled, not attachable)",
     "add it through the editor — never hand-write a .meta"),
    ("orphan-meta", "a .meta whose asset is gone (deleted outside the editor)",
     "delete through the editor, or remove the stray record there"),
    ("broken-script-ref", "m_Script: {fileID: 0} — a component bound to nothing",
     "reassign the script in the inspector; the object does nothing at runtime today"),
    ("unwired", "a behaviour whose GUID appears in no scene, prefab or asset",
     "a QUESTION, not a defect: dead code, or a feature still being built?"),
)


def run(root: Path) -> Dict[str, List[str]]:
    files = _walk(root)
    return {
        "no-meta": find_source_without_meta(files, root),
        "orphan-meta": find_orphan_meta(files, root),
        "broken-script-ref": find_broken_script_refs(files, root),
        "unwired": find_unwired(files, root),
    }


def main(argv: Optional[List[str]] = None) -> int:
    _utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="Assets",
                        help="first-party source root (default: Assets)")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print("not a directory: {} — pass --root for projects that keep first-party code "
              "elsewhere".format(root.as_posix()), file=sys.stderr)
        return 2

    findings = run(root)

    if args.as_json:
        import json as _json
        print(_json.dumps({"root": root.as_posix(), "findings": findings}, indent=2))
        return 1 if any(findings.values()) else 0

    total = 0
    for key, what, fix in CHECKS:
        hits = findings[key]
        if not hits:
            continue
        # `unwired` is a question, so it is shown but does not decide the exit code.
        if key != "unwired":
            total += len(hits)
        print()
        print("{} ({}) — {}".format(key, len(hits), what))
        print("  fix: {}".format(fix))
        for item in hits[:20]:
            print("    {}".format(item))
        if len(hits) > 20:
            print("    ... and {} more".format(len(hits) - 20))

    print()
    print("asset integrity: {} problem(s), {} question(s) under {}".format(
        total, len(findings["unwired"]), root.as_posix()))
    if total:
        print("none of these fail a build or a test — that is why they are checked here",
              file=sys.stderr)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
