"""Pytest setup for the hephaestus suite.

The cms scripts are written as flat modules that do `from common import ...`, so the
scripts directory must be importable. We also redirect cms state to a temp dir so importing
`common` doesn't write into the plugin's real state directory.
"""
from __future__ import annotations

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

# Isolate cms state writes (common.py creates STATE_DIR at import time).
import os

os.environ.setdefault("CMS_STATE_DIR", tempfile.mkdtemp(prefix="hephaestus-cms-state-"))

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
