"""Pytest setup for the hephaestus suite.

The cms scripts are written as flat modules that do `from common import ...`, so the
scripts directory must be importable. We also redirect cms state to a temp dir so importing
`common` doesn't write into the plugin's real state directory.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

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


# --------------------------------------------------------------------------- git fixtures
#
# Document ages are resolved from git committer dates, not mtimes, because git neither
# records nor restores mtimes — so every test that manufactured an old file with
# `os.utime` was asserting against a filesystem state git never produces, and the archive
# rule was able to be entirely broken on every clone while the suite stayed green. This
# fixture makes "an old document" mean the only thing it can honestly mean: a real commit
# with a real, backdated committer date.


class GitDocRepo:
    """A throwaway git repository whose files have genuine commit dates."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _git(self, *args: str, when: str = None) -> None:
        env = dict(os.environ)
        env.setdefault("GIT_CONFIG_NOSYSTEM", "1")
        if when:
            env["GIT_COMMITTER_DATE"] = when
            env["GIT_AUTHOR_DATE"] = when
        subprocess.run(
            ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=Test",
             "-c", "commit.gpgsign=false", *args],
            cwd=str(self.path), env=env, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace",
        )

    def commit(self, rel: str, body: str, age: int) -> Path:
        """Write `rel` and commit it `age` days in the past.

        The file's mtime is *now* — deliberately. Only git knows it is old, which is
        exactly the condition a fresh clone produces and `os.utime` never does.
        """
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        when = (date.today() - timedelta(days=age)).isoformat() + "T12:00:00+00:00"
        self._git("add", "--", rel)
        self._git("commit", "--quiet", "-m", f"add {rel}", when=when)
        return target


@pytest.fixture
def git_doc_repo(tmp_path):
    """An initialised git repo with a docs/ dir, plus a `.commit(rel, body, age)` helper."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", "repo"], cwd=str(tmp_path), check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    made = GitDocRepo(repo)
    yield made
    import doc_age
    doc_age.clear_cache()  # the module memoizes per repo root; every test builds a new one
