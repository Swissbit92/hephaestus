"""Pytest setup for the whetstone suite.

The cms scripts are written as flat modules that do `from common import ...`, so the
scripts directory must be importable. We also redirect cms state to a temp dir so importing
`common` doesn't write into the plugin's real state directory.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CMS_SCRIPTS = REPO_ROOT / "plugins" / "whetstone" / "skills" / "cms" / "scripts"
SCRIPTS = REPO_ROOT / "scripts"

# Isolate cms state writes (common.py creates STATE_DIR at import time).
import os

os.environ.setdefault("CMS_STATE_DIR", tempfile.mkdtemp(prefix="whetstone-cms-state-"))

# Make the cms scripts importable as top-level modules (common, check, hook, ...).
if str(CMS_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(CMS_SCRIPTS))

# Make repo-level scripts importable (bump_version, ...).
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
