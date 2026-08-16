"""Tests for the SKILL.md PreToolUse hook.

The hook exists because placement was measured in this repo: asking an agent to run a
check caught a defect 2/6, having the harness run it caught 3/3. A CI-only lint is the
first placement. These pin the properties that make the second one safe to live with.

The cases that make it non-trivial, each of which would make the hook worse than nothing:

- it must judge the content the write *would produce*, not the file already on disk —
  checking the latter tests the document being replaced and passes exactly when it
  should not;
- an ERROR blocks and a WARN does not, because blocking a write for being 40 tokens over
  budget makes it impossible to add a section in two edits, and a gate that fires
  mid-thought is one people switch off;
- it must fail open on anything it cannot determine, since a broken hook would otherwise
  become a broken editor;
- it must ignore files that are not SKILL.md and paths outside its roots, or every edit
  in every unrelated project pays for it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "plugins" / "crucible" / "scripts" / "skill_lint_hook.py"

GOOD = "---\nname: alpha\ndescription: Does one thing. Use when that thing is needed.\n---\n\nBody.\n"
NO_DESC = "---\nname: alpha\n---\n\nBody.\n"


def _fire(payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(payload),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(cwd), env={**_env(), "SKILL_LINT_ROOTS": str(cwd)}, timeout=60)


def _env() -> dict:
    import os
    return dict(os.environ)


def _write_payload(path: Path, content: str) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}}


def _skill_path(root: Path, name: str = "alpha") -> Path:
    p = root / "skills" / name / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# --------------------------------------------------------------------------- scope
def test_a_non_skill_file_is_waved_through(tmp_path):
    p = tmp_path / "README.md"
    assert _fire(_write_payload(p, "# not a skill\n"), tmp_path).returncode == 0


def test_a_non_write_tool_is_waved_through(tmp_path):
    p = _skill_path(tmp_path)
    payload = {"tool_name": "Read", "tool_input": {"file_path": str(p)}}
    assert _fire(payload, tmp_path).returncode == 0


def test_a_skill_outside_the_configured_roots_is_waved_through(tmp_path):
    """Editing an unrelated project must not be gated by whichever repo happens to be cwd."""
    other = tmp_path / "elsewhere"
    p = _skill_path(other)
    r = subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(_write_payload(p, NO_DESC)),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**_env(), "SKILL_LINT_ROOTS": str(tmp_path / "somewhere-else")}, timeout=60)
    assert r.returncode == 0


# --------------------------------------------------------------------------- blocking
def test_missing_description_blocks_the_write(tmp_path):
    p = _skill_path(tmp_path)
    r = _fire(_write_payload(p, NO_DESC), tmp_path)
    assert r.returncode == 2
    assert "description" in r.stderr


def test_name_disagreeing_with_directory_blocks(tmp_path):
    p = _skill_path(tmp_path, "alpha")
    bad = "---\nname: beta\ndescription: Does a thing. Use when needed.\n---\n\nBody.\n"
    r = _fire(_write_payload(p, bad), tmp_path)
    assert r.returncode == 2
    assert "directory" in r.stderr


def test_a_valid_skill_passes_silently(tmp_path):
    p = _skill_path(tmp_path)
    r = _fire(_write_payload(p, GOOD), tmp_path)
    assert r.returncode == 0 and r.stderr.strip() == ""


# --------------------------------------------------------------------------- the proposed content
def test_it_judges_the_proposed_content_not_the_file_on_disk(tmp_path):
    """The property the whole hook depends on. A valid file on disk being overwritten with
    an invalid one must block — reading the existing file would report the document the
    edit is about to destroy, and pass."""
    p = _skill_path(tmp_path)
    p.write_text(GOOD, encoding="utf-8")
    r = _fire(_write_payload(p, NO_DESC), tmp_path)
    assert r.returncode == 2, "checked the old content instead of the proposed content"


def test_an_edit_that_repairs_a_broken_skill_is_allowed(tmp_path):
    """The mirror case: a file that is currently invalid must not be un-editable."""
    p = _skill_path(tmp_path)
    p.write_text(NO_DESC, encoding="utf-8")
    payload = {"tool_name": "Edit", "tool_input": {
        "file_path": str(p), "old_string": "name: alpha\n",
        "new_string": "name: alpha\ndescription: Does one thing. Use when needed.\n"}}
    assert _fire(payload, tmp_path).returncode == 0


def test_an_ambiguous_edit_is_not_judged(tmp_path):
    """A non-unique old_string is a failing edit anyway; guessing at the result and
    blocking on the guess would complain about a document that never existed."""
    p = _skill_path(tmp_path)
    p.write_text(GOOD + "repeat\nrepeat\n", encoding="utf-8")
    payload = {"tool_name": "Edit", "tool_input": {
        "file_path": str(p), "old_string": "repeat\n", "new_string": ""}}
    assert _fire(payload, tmp_path).returncode == 0


# --------------------------------------------------------------------------- severity split
def test_an_oversized_skill_warns_without_blocking(tmp_path):
    """A budget overrun is real and worth saying at the moment it appears — but blocking
    it would make adding a section in two edits impossible."""
    import skill_lint as sl
    p = _skill_path(tmp_path)
    big = GOOD + ("word " * (sl.TOKEN_WARN * 4))
    r = _fire(_write_payload(p, big), tmp_path)
    assert r.returncode == 0, "a token-budget warning must never block"
    assert "tokens" in r.stderr


def test_errors_and_warnings_are_reported_together_when_blocking(tmp_path):
    p = _skill_path(tmp_path)
    import skill_lint as sl
    both = NO_DESC + ("word " * (sl.TOKEN_WARN * 4))
    r = _fire(_write_payload(p, both), tmp_path)
    assert r.returncode == 2
    assert "description" in r.stderr and "tokens" in r.stderr


# --------------------------------------------------------------------------- failing open
def test_unparseable_payload_allows_the_write(tmp_path):
    r = subprocess.run([sys.executable, str(HOOK)], input="not json at all",
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    assert r.returncode == 0


def test_a_payload_without_a_file_path_allows_the_write(tmp_path):
    assert _fire({"tool_name": "Write", "tool_input": {}}, tmp_path).returncode == 0
