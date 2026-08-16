"""Tests for the standing-constraint runner.

The mechanism exists because a constraint stated once is least salient exactly when it is
about to be broken. So the property that matters most is the one asserted in
`test_verdict_is_independent_of_how_the_task_was_described`: the outcome must not depend on
whether anyone remembered, restated, or even mentioned the rule.

The rest pin the three silences apart — no file, no wired check, and checks that ran and
passed are three different situations and only the last is evidence.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugins" / "crucible" / "scripts" / "invariants_run.py"


def _load():
    spec = importlib.util.spec_from_file_location("invariants_run", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ir = _load()

ENTRY = """## {title}

Status: {status}
Statement: {statement}
Falsifiable: WHEN x THE SYSTEM SHALL y
Check: {check}
"""


def _repo(tmp_path: Path, *entries: str, check_body: str | None = None,
          check_name: str = "checks/c.py") -> Path:
    repo = tmp_path / "r"
    (repo / "docs").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "INVARIANTS.md").write_text(
        "# Invariants\n\n" + "\n".join(entries), encoding="utf-8")
    if check_body is not None:
        p = repo / check_name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(check_body, encoding="utf-8")
    return repo


def _run(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo)],
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)


# --------------------------------------------------------------------------- parsing
def test_parse_reads_fields_per_entry():
    text = (ENTRY.format(title="A", status="active", statement="s1", check="checks/a.py")
            + ENTRY.format(title="B", status="retired", statement="s2", check="none yet"))
    a, b = ir.parse(text)
    assert (a.title, a.is_active, a.has_check) == ("A", True, True)
    assert (b.title, b.is_active, b.has_check) == ("B", False, False)


def test_none_yet_variants_all_count_as_unwired():
    for val in ("none yet", "none", "TODO", "TBD", "-", "n/a", ""):
        e = ir.parse(ENTRY.format(title="A", status="active", statement="s", check=val))[0]
        assert e.has_check is False, f"{val!r} must not count as a wired check"


def test_prose_around_entries_is_ignored():
    """The file has to stay a document someone wants to read, not a config to appease."""
    text = ("# Invariants\n\nSome explanatory prose.\n\n"
            + ENTRY.format(title="A", status="active", statement="s", check="checks/a.py")
            + "\nA closing note that mentions Status: nonsense in passing.\n")
    entries = ir.parse(text)
    assert len(entries) == 1 and entries[0].title == "A"


# --------------------------------------------------------------------------- exit codes
def test_exit_3_when_no_file(tmp_path):
    repo = tmp_path / "empty"
    (repo / "docs").mkdir(parents=True)
    p = _run(repo)
    assert p.returncode == 3
    assert "SKIP, not a pass" in (p.stdout + p.stderr)


def test_exit_3_when_stated_but_never_wired(tmp_path):
    """The most dangerous state: constraints exist, nothing enforces them. Reporting that
    as a pass would be worse than having no file at all — it would look like coverage."""
    repo = _repo(tmp_path, ENTRY.format(title="Mobile-first", status="active",
                                        statement="usable at phone width", check="none yet"))
    p = _run(repo)
    assert p.returncode == 3
    combined = p.stdout + p.stderr
    assert "SKIP, not a pass" in combined
    assert "stated but nothing prevents its violation" in combined or "is a wish" in combined


def test_exit_0_when_a_wired_check_passes(tmp_path):
    repo = _repo(tmp_path,
                 ENTRY.format(title="Holds", status="active", statement="s", check="checks/c.py"),
                 check_body="import sys\nsys.exit(0)\n")
    p = _run(repo)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "ok" in p.stdout


def test_exit_1_when_a_wired_check_fails(tmp_path):
    repo = _repo(tmp_path,
                 ENTRY.format(title="Mobile-first", status="active",
                              statement="usable at phone width", check="checks/c.py"),
                 check_body="import sys\nprint('375px viewport scrolls horizontally')\nsys.exit(1)\n")
    p = _run(repo)
    assert p.returncode == 1
    combined = p.stdout + p.stderr
    assert "INVARIANT VIOLATED" in combined
    assert "Mobile-first" in combined


def test_exit_2_when_the_check_path_is_missing(tmp_path):
    """A check that could not run is not a check that passed."""
    repo = _repo(tmp_path, ENTRY.format(title="A", status="active", statement="s",
                                        check="checks/does_not_exist.py"))
    p = _run(repo)
    assert p.returncode == 2
    assert "cannot determine" in (p.stdout + p.stderr)


def test_retired_entries_are_not_run(tmp_path):
    repo = _repo(tmp_path,
                 ENTRY.format(title="Old", status="retired", statement="s", check="checks/c.py"),
                 check_body="import sys\nsys.exit(1)\n")
    p = _run(repo)
    assert p.returncode == 3, "a retired invariant must not be enforced"


def test_one_failure_among_passes_still_fails(tmp_path):
    repo = tmp_path / "r"
    (repo / "docs").mkdir(parents=True)
    (repo / "checks").mkdir(parents=True)
    (repo / "checks" / "ok.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    (repo / "checks" / "bad.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    (repo / "docs" / "INVARIANTS.md").write_text(
        "# Invariants\n\n"
        + ENTRY.format(title="Fine", status="active", statement="s", check="checks/ok.py")
        + ENTRY.format(title="Broken", status="active", statement="s", check="checks/bad.py"),
        encoding="utf-8")
    p = _run(repo)
    assert p.returncode == 1
    assert "Broken" in (p.stdout + p.stderr)


# --------------------------------------------------------------------------- the point
def test_verdict_is_independent_of_how_the_task_was_described(tmp_path):
    """The reason this is a script and not an instruction.

    A constraint carried in prose decays as a session grows — it competes with everything
    said since and is least salient exactly when it is about to be broken. Here the same
    violating repo is evaluated with no prompt, no restatement, and no mention of the rule
    at all, and the verdict is identical, because nothing in this path consults a
    description of the task.
    """
    repo = _repo(tmp_path,
                 ENTRY.format(title="Mobile-first", status="active",
                              statement="usable at phone width", check="checks/c.py"),
                 check_body="import sys\nsys.exit(1)\n")
    verdicts = {_run(repo).returncode for _ in range(3)}
    assert verdicts == {1}, "the outcome must not vary with context, only with the code"
