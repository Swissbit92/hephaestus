#!/usr/bin/env python3
"""Semver bump helper for the hephaestus release flow. Pure stdlib.

Extracted from release.sh so the version math is unit-testable. Given a current
X.Y.Z version and a bump spec, returns/prints the next version.

Usage:
    bump_version.py <current X.Y.Z> <patch|minor|major|X.Y.Z>
"""
from __future__ import annotations

import re
import sys

_SEMVER = re.compile(r"\d+\.\d+\.\d+")


def next_version(current: str, bump: str) -> str:
    """Return the next version string. Raise ValueError on bad input.

    `bump` is one of patch|minor|major, or an explicit X.Y.Z (returned as-is).
    """
    bump = bump.strip()
    if _SEMVER.fullmatch(bump):
        return bump  # explicit version pin
    current = current.strip()
    if not _SEMVER.fullmatch(current):
        raise ValueError(f"current version not X.Y.Z: {current!r}")
    major, minor, patch = (int(x) for x in current.split("."))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise ValueError(f"invalid bump: {bump!r} (use patch|minor|major|X.Y.Z)")


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: bump_version.py <current X.Y.Z> <patch|minor|major|X.Y.Z>\n")
        return 2
    try:
        print(next_version(argv[0], argv[1]))
    except ValueError as e:
        sys.stderr.write(f"{e}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
