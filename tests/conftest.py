"""Pytest setup for the hephaestus suite.

The cms scripts are written as flat modules that do `from common import ...`, so the
scripts directory must be importable. We also redirect cms state to a temp dir so importing
`common` doesn't write into the plugin's real state directory.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CMS_SCRIPTS = REPO_ROOT / "plugins" / "crucible" / "skills" / "cms" / "scripts"
SCRIPTS = REPO_ROOT / "scripts"
SQLITE_RO = REPO_ROOT / "plugins" / "sqlite-readonly" / "servers" / "sqlite-readonly"
DECK_LIB = REPO_ROOT / "plugins" / "deck-builder" / "skills" / "deck-builder"
EVALS = REPO_ROOT / "evals"
EVAL_FIRST_SCRIPTS = REPO_ROOT / "plugins" / "crucible" / "skills" / "eval-first" / "scripts"
LOOP_HARNESS_SCRIPTS = REPO_ROOT / "plugins" / "crucible" / "skills" / "loop-harness" / "scripts"
REPO_AUDIT_SCRIPTS = REPO_ROOT / "plugins" / "crucible" / "skills" / "repo-audit" / "scripts"
SECOND_BRAIN_SCRIPTS = (REPO_ROOT / "plugins" / "second-brain" / "skills"
                        / "second-brain" / "scripts")
CRUCIBLE_SCRIPTS = REPO_ROOT / "plugins" / "crucible" / "scripts"

# Isolate cms + loop-harness state writes. Both `common.py` and `loop_common.py` resolve
# *and* mkdir their STATE_DIR at module import, and test modules import them during
# collection — so this has to run here, at import time and above the sys.path inserts.
# A fixture would be far too late.
_OWNED_TEMP_DIRS: list[str] = []


def _isolate_state_dir(var: str, prefix: str) -> None:
    """Point `var` at a throwaway temp dir, but only when it isn't already set.

    `os.environ.setdefault(var, tempfile.mkdtemp(...))` reads correctly and behaves
    wrongly: Python evaluates the argument *before* setdefault can decline it, so a
    directory got created on every run — including every run that then threw it away.
    Two per pytest process, never removed, which is how ~490 empty dirs accumulated in
    %TEMP% on this machine between 2026-07-17 and 2026-08-16.
    """
    if os.environ.get(var):
        return
    path = tempfile.mkdtemp(prefix=prefix)
    os.environ[var] = path
    _OWNED_TEMP_DIRS.append(path)


_isolate_state_dir("CMS_STATE_DIR", "hephaestus-cms-state-")
_isolate_state_dir("LOOP_HARNESS_STATE_DIR", "hephaestus-loop-state-")

# Make the cms scripts importable as top-level modules (common, check, hook, ...).
if str(CMS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CMS_SCRIPTS))

# Make repo-level scripts importable (bump_version, ...).
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# Make the sqlite-readonly package importable (sqlite_readonly.validator, ...).
if str(SQLITE_RO) not in sys.path:
    sys.path.insert(0, str(SQLITE_RO))

# Make deck_lib importable (pure helpers; python-pptx imported lazily inside Deck).
if str(DECK_LIB) not in sys.path:
    sys.path.insert(0, str(DECK_LIB))

# Make the eval harness importable (from harness import scoring, reliability, ...).
if str(EVALS) not in sys.path:
    sys.path.insert(0, str(EVALS))

# Make the eval-first crucible skill scripts importable (ab_harness, baseline, judge, ...).
if str(EVAL_FIRST_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(EVAL_FIRST_SCRIPTS))

# Make the loop-harness crucible skill scripts importable (loop_common, loop_budget, ...).
if str(LOOP_HARNESS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(LOOP_HARNESS_SCRIPTS))

# Make the repo-audit crucible skill scripts importable (repo_metrics).
if str(REPO_AUDIT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(REPO_AUDIT_SCRIPTS))

# Make the second-brain skill scripts importable (vault_graph).
if str(SECOND_BRAIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SECOND_BRAIN_SCRIPTS))

# Make the crucible plugin-level scripts importable (new_skill). These ship inside the
# plugin so the paths its skills document resolve for installed users, not just here.
if str(CRUCIBLE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CRUCIBLE_SCRIPTS))


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests marked `requires_claude` when the claude CLI is absent (so the live
    skill-eval tests don't fail in a headless CI that only runs the pure suite)."""
    import shutil

    import pytest

    if shutil.which("claude"):
        return
    skip = pytest.mark.skip(reason="claude CLI not available")
    for item in items:
        if "requires_claude" in item.keywords:
            item.add_marker(skip)


def pytest_unconfigure(config):
    """Remove only the temp dirs *this* process created — never a caller-supplied one.

    `ignore_errors=True` is load-bearing rather than defensive: the Windows CI leg
    occasionally still holds a handle on `size_history.json` as the session ends, and a
    cleanup failure must not turn a green run red.
    """
    while _OWNED_TEMP_DIRS:
        shutil.rmtree(_OWNED_TEMP_DIRS.pop(), ignore_errors=True)
