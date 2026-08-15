#!/usr/bin/env python3
"""Report which verification gates a repository actually supports, and where.

A workflow that runs one hardcoded gate is wrong in both directions: it runs commands a
project does not have, and it misses the ones it does. This walks a repo, finds every
*project root* (a directory carrying its own manifest), and reports the gates each one
supports — so the caller runs the right checks per root instead of one guess at the top.

Reports; never executes. Reading a repo's declared scripts is safe, running them is a
supply-chain decision that belongs to the caller, not to a detector.

Detection is evidence-based: when no marker is found it says so rather than guessing a
command that would fail confusingly or, worse, pass vacuously.

Exit codes:
    0 — at least one project root found; gates listed
    2 — could not determine (unreadable path, malformed manifest). NOT a pass.
    3 — no markers anywhere: nothing to gate. NOT a pass, and not evidence of health.
    1 — unused. There is no "regression" for a detector; kept free so the code never
        reads as one by analogy with the sibling Phase-4.0 scripts.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

PRUNE = {".venv", "venv", "__pycache__", ".git", "node_modules", ".tox",
         "dist", "build", ".mypy_cache", ".pytest_cache", "site-packages"}


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


def python_token() -> str:
    """The interpreter token to embed in an emitted, shell-runnable gate command.

    On POSIX this stays the bare name `python3`, so an activated venv still wins at run
    time and the emitted line stays readable.

    On Windows it becomes this interpreter's own absolute path, because no name is
    trustworthy there: `shutil.which("python3")` normally *succeeds* by finding the
    Microsoft Store App Execution Alias in `WindowsApps`, which is not an interpreter —
    it prints an install ad and exits without running anything. A which() check therefore
    cannot tell a working `python3` from that stub, and a gate line that cannot run is
    not a gate. Forward slashes are used because these lines are executed through a
    POSIX-ish shell (Git Bash), where a backslash is an escape character.
    """
    if sys.platform == "win32":
        exe = Path(sys.executable).as_posix() if sys.executable else ""
        if exe:
            return f'"{exe}"' if " " in exe else exe
    if shutil.which("python3"):
        return "python3"
    return "python"

# Gate  = runnable now, hermetic, deterministic.
# Capability = present but needs a live service or browser; reported, never auto-gated,
#              because an e2e run against nothing collects zero tests and "zero tests
#              passed" is the classic vacuous green.
GATE, CAPABILITY = "gate", "capability"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# --------------------------------------------------------------------------- python
def _pytest_config(root: Path) -> tuple[bool, str]:
    """(has_pytest_config, where). Config lives in four different shapes in the wild, so
    file existence alone answers the wrong question."""
    pp = root / "pyproject.toml"
    if pp.exists() and "[tool.pytest.ini_options]" in _read(pp):
        return True, "pyproject.toml [tool.pytest.ini_options]"
    if (root / "pytest.ini").exists():
        return True, "pytest.ini"
    cfg = root / "setup.cfg"
    if cfg.exists() and re.search(r"^\[tool:pytest\]", _read(cfg), re.M):
        return True, "setup.cfg [tool:pytest]"
    if (root / "tox.ini").exists() and re.search(r"^\[pytest\]", _read(root / "tox.ini"), re.M):
        return True, "tox.ini [pytest]"
    return False, ""


def _python_profile(root: Path, rel: str) -> dict | None:
    pp = root / "pyproject.toml"
    has_cfg, where = _pytest_config(root)
    has_tests = (root / "tests").is_dir()
    # A project with neither a manifest nor a tests/ dir is not a Python project we can gate.
    if not pp.exists() and not has_cfg and not has_tests:
        return None
    if not pp.exists() and not has_cfg and has_tests and not (root / "requirements.txt").exists():
        return None

    gates, notes = [], []
    if has_cfg or has_tests:
        py = python_token()
        gates.append({"name": "tests", "cmd": f"{py} -m pytest", "kind": GATE,
                      "source": where or "tests/ directory (no pytest config found)"})
        gates.append({"name": "coverage-delta", "kind": GATE,
                      "cmd": f'{py} "$CRUCIBLE_SCRIPTS/coverage_delta.py" --repo {rel or "."}',
                      "source": "crucible"})
    if not has_cfg and has_tests:
        notes.append("no pytest config found; the bare command may pick a different rootdir "
                     "than the project intends")

    pp_text = _read(pp) if pp.exists() else ""
    if "[tool.ruff]" in pp_text or (root / ".ruff.toml").exists() or (root / "ruff.toml").exists():
        gates.append({"name": "lint", "cmd": "ruff check .", "kind": GATE, "source": "ruff config"})
        if "[tool.ruff.format]" in pp_text or "[tool.ruff]" in pp_text:
            gates.append({"name": "format", "cmd": "ruff format --check .", "kind": GATE,
                          "source": "ruff config"})
    if "[tool.mypy]" in pp_text or (root / "mypy.ini").exists():
        gates.append({"name": "typecheck", "cmd": "mypy .", "kind": GATE, "source": "mypy config"})
    if (root / ".pre-commit-config.yaml").exists():
        gates.append({"name": "pre-commit", "cmd": "pre-commit run --all-files", "kind": GATE,
                      "source": ".pre-commit-config.yaml"})
        notes.append("pre-commit may duplicate or extend the lint gate — check its hooks list "
                     "rather than assuming it is the same ruff run")

    m = re.search(r"--cov-fail-under[= ](\d+)", pp_text)
    if m:
        notes.append(f"declares a coverage threshold of {m.group(1)}% — read from config, "
                     "not imposed; it is already inside the project's own test command")
    if not gates:
        return None
    return {"root": rel or ".", "kind": "python", "gates": gates, "notes": notes}


# --------------------------------------------------------------------------- node
def _node_profile(root: Path, rel: str) -> dict | None:
    pkg = root / "package.json"
    try:
        data = json.loads(_read(pkg))
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"{rel or '.'}/package.json is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{rel or '.'}/package.json is not an object")

    scripts = data.get("scripts") or {}
    # Check BOTH dependency maps. Some scaffolds put typescript/eslint/jest/testing-library
    # in `dependencies`; keying on devDependencies alone reports a fully-tooled app as
    # having no gates at all.
    deps = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        d = data.get(key)
        if isinstance(d, dict):
            deps.update(d)

    gates, notes = [], []
    if "build" in scripts:
        gates.append({"name": "build", "cmd": "npm run build", "kind": GATE, "source": "scripts.build"})
        if (root / "tsconfig.json").exists():
            notes.append("build also typechecks when the toolchain wires tsc into it; if it "
                         "does not, add `tsc --noEmit`")
    elif (root / "tsconfig.json").exists() or "typescript" in deps:
        gates.append({"name": "typecheck", "cmd": "npx tsc --noEmit", "kind": GATE,
                      "source": "tsconfig.json"})

    if "lint" in scripts:
        gates.append({"name": "lint", "cmd": "npm run lint", "kind": GATE, "source": "scripts.lint"})
    elif "eslint" in deps or "eslintConfig" in data or any(
            (root / f).exists() for f in (".eslintrc", ".eslintrc.json", ".eslintrc.cjs",
                                          "eslint.config.js", "eslint.config.mjs")):
        gates.append({"name": "lint", "cmd": "npx eslint .", "kind": GATE, "source": "eslint config"})

    if "test" in scripts:
        gates.append({"name": "tests", "cmd": "npm test", "kind": GATE, "source": "scripts.test"})
    elif "vitest" in deps:
        gates.append({"name": "tests", "cmd": "npx vitest run", "kind": GATE, "source": "vitest dep"})
    elif "jest" in deps:
        gates.append({"name": "tests", "cmd": "npx jest", "kind": GATE, "source": "jest dep"})

    # e2e: a capability, not a gate. Config may assume a server is already listening.
    if "@playwright/test" in deps:
        cfgs = [f for f in ("playwright.config.ts", "playwright.config.js", "playwright.config.mjs")
                if (root / f).exists()]
        if cfgs:
            txt = _read(root / cfgs[0])
            has_server = "webServer" in txt
            gates.append({"name": "e2e", "cmd": "npx playwright test",
                          "kind": GATE if has_server else CAPABILITY, "source": cfgs[0]})
            if not has_server:
                notes.append(f"{cfgs[0]} declares no webServer — it expects the app to be "
                             "running already, so this is a capability, not a gate. Running it "
                             "against nothing yields zero tests, and zero tests passing is not "
                             "a pass.")
        else:
            notes.append("@playwright/test is installed but no playwright config was found — "
                         "installed is not wired; not gated")
    if not gates:
        return None
    return {"root": rel or ".", "kind": "node", "gates": gates, "notes": notes}


# --------------------------------------------------------------------------- walk
def detect(repo: Path, max_depth: int = 3) -> list[dict]:
    """Every project root at or below `repo`, each with its own gates.

    A repo may legitimately contain several independent projects, so this does not stop at
    the first match — stopping there is precisely how a frontend or a sibling service ends
    up ungated while the top-level report says everything is covered.
    """
    profiles: list[dict] = []
    repo = repo.resolve()

    def visit(d: Path, depth: int) -> None:
        # as_posix(), not str(): this value is a machine-readable identifier that lands in
        # JSON, in emitted `--repo <rel>` gate lines, and in test assertions. str() yields
        # "services\gw" on Windows, which is neither comparable across platforms nor safe
        # to paste into a shell command where the backslash is an escape.
        rel = "" if d == repo else d.relative_to(repo).as_posix()
        py = _python_profile(d, rel)
        if py:
            profiles.append(py)
        if (d / "package.json").exists():
            node = _node_profile(d, rel)
            if node:
                profiles.append(node)
        if depth >= max_depth:
            return
        try:
            children = sorted(x for x in d.iterdir() if x.is_dir())
        except OSError:
            return
        for child in children:
            if child.name in PRUNE or child.name.startswith("."):
                continue
            visit(child, depth + 1)

    visit(repo, 0)
    return profiles


def render(profiles: list[dict]) -> str:
    lines = []
    for p in profiles:
        lines.append(f"[{p['kind']}] {p['root']}")
        for g in p["gates"]:
            tag = "" if g["kind"] == GATE else "  (capability — needs a live service)"
            lines.append(f"    {g['name']:14} {g['cmd']}{tag}")
        for n in p.get("notes", []):
            lines.append(f"    note: {n}")
    return "\n".join(lines)


def emit_gates(profiles: list[dict]) -> tuple[str, str]:
    """(runnable, notes). Only `gate`s become commands.

    This is what makes the gate/capability split load-bearing rather than decorative: a
    capability is never emitted, so it cannot be run by accident against a service that
    is not up — which would collect nothing and exit clean, the precise shape of a
    vacuous pass. Capabilities are reported on stderr, where they inform without gating.
    """
    runnable, notes = [], []
    for p in profiles:
        root = p["root"]
        for g in p["gates"]:
            if g["kind"] != GATE:
                notes.append(f"capability (not gated) — {root}: {g['name']}: {g['cmd']}")
                continue
            prefix = "" if root == "." else f"cd {root} && "
            runnable.append(f"{prefix}{g['cmd']}")
        for n in p.get("notes", []):
            notes.append(f"note — {root}: {n}")
    return "\n".join(runnable), "\n".join(notes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".", help="repository path (default: cwd)")
    ap.add_argument("--max-depth", type=int, default=3,
                    help="how deep to look for nested project roots (default: 3)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a report")
    ap.add_argument("--emit-gates", action="store_true",
                    help="print one runnable command per line (gates only; capabilities "
                         "and notes go to stderr). Exit 3 if nothing is runnable.")
    a = ap.parse_args(argv)

    repo = Path(a.repo)
    if not repo.is_dir():
        print(f"cannot determine profiles: {repo} is not a directory", file=sys.stderr)
        return 2
    try:
        profiles = detect(repo, a.max_depth)
    except ValueError as e:
        print(f"cannot determine profiles: {e}", file=sys.stderr)
        return 2

    if not profiles:
        print("no project markers found — nothing to gate here.\n"
              "This is a SKIP, not a pass: it says the detector found no evidence, not that "
              "the code is healthy. Pass --collect-cmd style gates explicitly if this repo "
              "has checks the markers do not advertise.", file=sys.stderr)
        return 3

    if a.emit_gates:
        runnable, notes = emit_gates(profiles)
        if notes:
            print(notes, file=sys.stderr)
        if not runnable:
            print("no runnable gates — every profile is capability-only.\n"
                  "This is a SKIP, not a pass: nothing was checked.", file=sys.stderr)
            return 3
        print(runnable)
        return 0

    print(json.dumps(profiles, indent=2) if a.json else render(profiles))
    return 0


if __name__ == "__main__":
    _utf8_stdio()
    raise SystemExit(main())
