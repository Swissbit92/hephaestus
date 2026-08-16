"""Tests for the release flow's version math (scripts/bump_version.py)."""
from __future__ import annotations

import pytest

from bump_version import next_version


@pytest.mark.parametrize(
    "current,bump,expected",
    [
        ("0.1.0", "patch", "0.1.1"),
        ("0.1.0", "minor", "0.2.0"),
        ("0.1.0", "major", "1.0.0"),
        ("0.2.0", "minor", "0.3.0"),
        ("1.2.3", "patch", "1.2.4"),
        ("1.9.9", "major", "2.0.0"),
        ("1.2.3", "minor", "1.3.0"),
    ],
)
def test_next_version_bumps(current, bump, expected):
    assert next_version(current, bump) == expected


@pytest.mark.parametrize("explicit", ["1.2.3", "10.0.1", "0.0.9"])
def test_next_version_explicit_pin(explicit):
    # An explicit X.Y.Z is returned verbatim regardless of current.
    assert next_version("0.1.0", explicit) == explicit


def test_next_version_strips_whitespace():
    assert next_version(" 0.1.0 ", " minor ") == "0.2.0"


@pytest.mark.parametrize("bump", ["sideways", "", "Patch", "1.2", "1.2.3.4"])
def test_next_version_rejects_bad_bump(bump):
    with pytest.raises(ValueError):
        next_version("0.1.0", bump)


@pytest.mark.parametrize("current", ["notsemver", "1.2", "v1.2.3", ""])
def test_next_version_rejects_bad_current(current):
    # Only matters when bump is relative (a valid explicit pin ignores current).
    with pytest.raises(ValueError):
        next_version(current, "patch")


# --------------------------------------------------------------------------- portability
# A release is the worst place for a half-executed script: it can leave a version bumped
# and untagged. release.sh used to guard with `command -v python3`, which SUCCEEDS on
# Windows by finding the Microsoft Store App Execution Alias — an ad printer that exits 49
# — so the guard passed and the next line died. These are static guards rather than
# behavioural ones because release.sh checks it is on `main` before it ever reaches the
# interpreter, so the path cannot be exercised from a feature branch.

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SHELL_SCRIPTS = sorted(p for p in REPO.glob("scripts/**/*.sh"))

# A bare `python`/`python3` used as a command, ignoring comments and `$PY`.
BARE_PYTHON = re.compile(r"^[^#\n]*(?<![\w$\"'/-])python3?\s", re.M)


def _uncommented(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_the_shell_scripts_this_repo_ships_are_discovered():
    """Guards the glob: an empty parametrize would make every check below pass vacuously."""
    names = {p.name for p in SHELL_SCRIPTS}
    assert {"release.sh", "_python.sh"} <= names, names


@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: p.name)
def test_no_shell_script_invokes_a_bare_python(script):
    """`_python.sh` is the one place allowed to name an interpreter, because it is the
    thing that probes them by execution rather than trusting a name."""
    if script.name == "_python.sh":
        pytest.skip("the resolver itself is where the names legitimately appear")
    hits = BARE_PYTHON.findall(_uncommented(script.read_text(encoding="utf-8")))
    assert not hits, (
        f"{script.name} invokes an interpreter by name; on Windows `python3` resolves to a "
        f"Store stub that runs nothing. Source scripts/checks/_python.sh and use \"$PY\".")


def test_release_sources_the_interpreter_resolver():
    text = (REPO / "scripts" / "release.sh").read_text(encoding="utf-8")
    assert "scripts/checks/_python.sh" in text
    assert '"$PY"' in text, "resolved interpreter must actually be used"


def test_the_resolver_exits_2_when_nothing_runs():
    """2, not 1: could-not-determine must never read as a failed check — and a release
    script that cannot find an interpreter has determined nothing."""
    text = (REPO / "scripts" / "checks" / "_python.sh").read_text(encoding="utf-8")
    assert "exit 2" in text
