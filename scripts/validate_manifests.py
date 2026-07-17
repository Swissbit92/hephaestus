#!/usr/bin/env python3
"""Validate the marketplace + plugin manifests without needing the `claude` CLI.

A CI-friendly stand-in for `claude plugin validate`: it JSON-loads every manifest and
checks the structural invariants that actually break installs — required keys, semver
versions, and that the marketplace and the per-plugin manifests agree (every listed
`source` exists, contains a plugin.json, and the names match).

Usage:
    python3 scripts/validate_manifests.py [REPO_ROOT]   # default: repo root of this script

Exit codes: 0 = all valid, 1 = one or more problems.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
_REQUIRED_PLUGIN_KEYS = ("name", "version", "description")


def _load_json(path: Path) -> tuple[dict | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"missing file: {path}"
    except (json.JSONDecodeError, ValueError) as e:
        return None, f"invalid JSON in {path}: {e}"


def validate(repo_root: Path) -> list[str]:
    """Return a list of problem strings (empty == valid)."""
    problems: list[str] = []
    repo_root = Path(repo_root)

    # --- per-plugin manifests
    plugin_manifests: dict[str, dict] = {}  # plugin dir name -> manifest
    plugins_dir = repo_root / "plugins"
    if not plugins_dir.is_dir():
        return [f"no plugins/ directory under {repo_root}"]

    for pdir in sorted(p for p in plugins_dir.iterdir() if p.is_dir()):
        manifest_path = pdir / ".claude-plugin" / "plugin.json"
        data, err = _load_json(manifest_path)
        if err:
            problems.append(err)
            continue
        plugin_manifests[pdir.name] = data
        for key in _REQUIRED_PLUGIN_KEYS:
            if key not in data:
                problems.append(f"{manifest_path}: missing required key '{key}'")
        ver = data.get("version", "")
        if not _SEMVER.match(str(ver)):
            problems.append(f"{manifest_path}: version {ver!r} is not semver X.Y.Z")

    # --- marketplace manifest
    mkt_path = repo_root / ".claude-plugin" / "marketplace.json"
    mkt, err = _load_json(mkt_path)
    if err:
        problems.append(err)
        return problems

    plugins = mkt.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        problems.append(f"{mkt_path}: 'plugins' must be a non-empty array")
        return problems

    seen_names: set[str] = set()
    for entry in plugins:
        name = entry.get("name", "<unnamed>")
        if name in seen_names:
            problems.append(f"{mkt_path}: duplicate plugin entry '{name}'")
        seen_names.add(name)
        source = entry.get("source", "")
        if not source:
            problems.append(f"{mkt_path}: plugin '{name}' has no source")
            continue
        src_dir = (repo_root / source).resolve()
        if not src_dir.is_dir():
            problems.append(f"{mkt_path}: plugin '{name}' source {source} is not a directory")
            continue
        src_manifest = src_dir / ".claude-plugin" / "plugin.json"
        if not src_manifest.is_file():
            problems.append(f"{mkt_path}: plugin '{name}' source {source} has no .claude-plugin/plugin.json")
            continue
        # name agreement between marketplace entry and the plugin's own manifest
        man = plugin_manifests.get(src_dir.name)
        if man is not None and man.get("name") != name:
            problems.append(
                f"{mkt_path}: entry name '{name}' != manifest name '{man.get('name')}' in {source}"
            )

    return problems


def main(argv: list[str]) -> int:
    repo_root = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent
    problems = validate(repo_root)
    if problems:
        print(f"✘ manifest validation FAILED ({len(problems)} problem(s)):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("✔ manifest validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
