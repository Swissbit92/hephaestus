"""The mtime invariant's own check.

The rule this enforces was learned in `render.py`, written down only in `render.py`'s
docstring, and then broken at four further sites — the last of which persisted a wrong
date into a file's frontmatter. So the check itself needs to be trustworthy in the two
ways a check of this shape usually is not:

- it must actually FAIL when the bug is reintroduced (a guard nobody has watched go red
  proves nothing when it is green), and
- it must NOT fire on prose. `doc_age.py`, the module that fixed the bug, discusses
  `st_mtime` at length in its docstring; a textual search would flag the remedy as the
  offence, and a rule that accuses its own fix is one people switch off.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import mtime_guard

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "mtime_guard.py"


def _parse(src: str) -> ast.AST:
    return ast.parse(src)


# --------------------------------------------------------------------------- detection
def test_attribute_read_is_detected():
    hits = mtime_guard.find_mtime_reads(_parse("age = path.stat().st_mtime\n"))
    assert [h[1] for h in hits] == [".st_mtime"]


def test_getmtime_call_is_detected():
    hits = mtime_guard.find_mtime_reads(_parse("import os\nage = os.path.getmtime(p)\n"))
    assert [h[1] for h in hits] == ["getmtime()"]


def test_ns_variant_is_detected():
    """st_mtime_ns is the same decision at higher resolution, not a different one."""
    hits = mtime_guard.find_mtime_reads(_parse("age = p.stat().st_mtime_ns\n"))
    assert [h[1] for h in hits] == [".st_mtime_ns"]


def test_prose_about_mtime_is_not_a_read():
    """The precise reason this parses rather than greps."""
    src = ('"""We used to read st_mtime here, and getmtime before that. Both were wrong."""\n'
           'MESSAGE = "do not use st_mtime"\n')
    assert mtime_guard.find_mtime_reads(_parse(src)) == []


def test_a_comment_mentioning_mtime_is_not_a_read():
    assert mtime_guard.find_mtime_reads(_parse("# st_mtime is a trap\nx = 1\n")) == []


# --------------------------------------------------------------------------- the real tree
def test_the_repository_currently_passes():
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(REPO_ROOT)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr


def test_doc_age_is_not_flagged_despite_discussing_mtime():
    """doc_age.py is the fix. If the guard flags it, the guard is the problem."""
    doc_age = (REPO_ROOT / "plugins" / "crucible" / "skills" / "cms" / "scripts"
               / "doc_age.py")
    text = doc_age.read_text(encoding="utf-8")
    assert "st_mtime" in text, "precondition: doc_age.py does discuss st_mtime in prose"
    assert mtime_guard.find_mtime_reads(ast.parse(text)) == []


def test_guard_fails_when_the_bug_is_reintroduced(tmp_path):
    """Mutation test. A guard that has never been observed failing is not a guard."""
    shipped = tmp_path / "plugins" / "demo" / "scripts"
    shipped.mkdir(parents=True)
    (shipped / "offender.py").write_text(
        "from pathlib import Path\n\n\ndef age(p):\n    return Path(p).stat().st_mtime\n",
        encoding="utf-8")

    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(tmp_path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")

    assert r.returncode == 1
    assert "offender.py" in r.stderr
    assert "git does not restore mtimes" in r.stderr


def test_allowlisted_file_is_permitted(tmp_path, monkeypatch):
    shipped = tmp_path / "plugins" / "demo" / "scripts"
    shipped.mkdir(parents=True)
    target = shipped / "local_tool.py"
    target.write_text("from pathlib import Path\n\n\ndef age(p):\n"
                      "    return Path(p).stat().st_mtime\n", encoding="utf-8")
    rel = "plugins/demo/scripts/local_tool.py"
    monkeypatch.setitem(mtime_guard.ALLOWED, rel, "operates on a local working directory")

    assert mtime_guard.main(["--repo", str(tmp_path)]) == 0


def test_unparseable_file_is_undetermined_not_a_pass(tmp_path):
    """The repo invariant that a check which could not run never reads as success."""
    shipped = tmp_path / "plugins" / "demo" / "scripts"
    shipped.mkdir(parents=True)
    (shipped / "broken.py").write_text("def (:\n", encoding="utf-8")

    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(tmp_path)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")

    assert r.returncode == 2, "a file that will not parse must not be reported as clean"
    assert "could not determine" in r.stderr


def test_every_allowlist_entry_states_a_reason():
    """The allowlist is only safe while the reasons are real; an empty one is a silencer."""
    for path, reason in mtime_guard.ALLOWED.items():
        assert len(reason.split()) >= 8, f"{path} has no substantive reason"
        assert (REPO_ROOT / path).exists(), f"{path} is allowlisted but no longer exists"
