"""Tests for the command files' referenced paths.

A command is prose until something runs it, and a workflow whose steps point at scripts
that moved is the exact failure this repo keeps naming: a check that cannot run reported as
a check. `develop` and `curate` both instruct an agent to execute
`${CLAUDE_PLUGIN_ROOT}/...` paths, and nothing else in the suite would notice one going
stale — the files that break are the ones nobody imports.

This is deliberately narrow. It does not test that the commands are good; it tests that
every path they tell an agent to run exists.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS = REPO_ROOT / "plugins"
COMMANDS = sorted(PLUGINS.glob("*/commands/*.md"))

# ${CLAUDE_PLUGIN_ROOT}/<path>.py, however it is quoted
REF_RE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_./-]+\.py)")


def _plugin_root(command_file: Path) -> Path:
    # plugins/<plugin>/commands/<file>.md -> plugins/<plugin>
    return command_file.parent.parent


@pytest.mark.parametrize("command_file", COMMANDS, ids=lambda p: p.name)
def test_every_referenced_script_exists(command_file):
    text = command_file.read_text(encoding="utf-8")
    root = _plugin_root(command_file)
    missing = [rel for rel in sorted(set(REF_RE.findall(text)))
               if not (root / rel).is_file()]
    assert not missing, (
        f"{command_file.relative_to(REPO_ROOT).as_posix()} tells an agent to run scripts "
        f"that do not exist: {missing}")


@pytest.mark.parametrize("command_file", COMMANDS, ids=lambda p: p.name)
def test_no_command_escapes_its_own_plugin_root(command_file):
    """`${CLAUDE_PLUGIN_ROOT}/../other-plugin/...` resolves in a checkout and not for an
    installed user, where plugins are not necessarily siblings on disk — so it works
    everywhere it is tested and nowhere it is used."""
    text = command_file.read_text(encoding="utf-8")
    assert "${CLAUDE_PLUGIN_ROOT}/.." not in text, (
        "a cross-plugin relative path is a checkout-only assumption")


def test_the_commands_this_repo_ships_are_discovered():
    """Guards the glob itself: if it silently matched nothing, both tests above would
    pass vacuously — the failure mode this repo has already been bitten by."""
    names = {c.name for c in COMMANDS}
    assert {"develop.md", "curate.md"} <= names, names
