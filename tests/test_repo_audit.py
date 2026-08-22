"""Tests for the repo-audit deterministic metrics (repo_metrics.py).

The whole reason this script exists is *reproducibility* — so these tests pin the exact
facts and the exact score arithmetic, and prove determinism (same input -> same output).
Pure stdlib; headless. Hermetic: every test passes an explicit `files` list so nothing
depends on git or the real tree.
"""
from __future__ import annotations

import json
from pathlib import Path

import repo_metrics as rm


def _tmp_py(source: str) -> Path:
    """A real file on disk holding `source` — the dead-module scan reads bodies."""
    import tempfile
    fh = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8")
    fh.write(source)
    fh.close()
    return Path(fh.name)


# --------------------------------------------------------------------------- helpers

def _write(root, rel, content):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content, encoding="utf-8")
    return rel


# --------------------------------------------------------------------------- inventory

def test_file_inventory_counts_bytes_and_lines(tmp_path):
    files = [
        _write(tmp_path, "a.py", "x = 1\ny = 2\n"),          # 2 lines
        _write(tmp_path, "b.py", "print('hi')"),              # 1 line (no trailing nl)
        _write(tmp_path, "README.md", "# hi\n"),              # non-source, 0 counted lines
    ]
    m = rm.collect(tmp_path, files=files)
    assert m.file_count == 3
    assert m.total_source_lines == 3  # 2 + 1, md not counted
    py = next(s for s in m.by_ext if s.ext == ".py")
    assert py.files == 2
    assert py.lines == 3


def test_binary_file_counts_zero_lines(tmp_path):
    files = [_write(tmp_path, "blob.py", b"\x00\x01\x02binary\x00")]
    m = rm.collect(tmp_path, files=files)
    assert m.total_source_lines == 0


# --------------------------------------------------------------------------- god files

def test_god_file_detection_and_threshold(tmp_path):
    big = "\n".join(f"line{i}" for i in range(600)) + "\n"      # 600 lines
    small = "\n".join(f"line{i}" for i in range(100)) + "\n"    # 100 lines
    files = [_write(tmp_path, "big.py", big), _write(tmp_path, "small.py", small)]
    m = rm.collect(tmp_path, files=files)
    assert [g.path for g in m.god_files] == ["big.py"]
    assert m.god_files[0].lines == 600
    # custom threshold pulls the small one in too, sorted by lines desc
    m2 = rm.collect(tmp_path, files=files, god_threshold=50)
    assert [g.path for g in m2.god_files] == ["big.py", "small.py"]


# --------------------------------------------------------------------------- artifacts

def test_tracked_artifacts_flagged(tmp_path):
    files = [
        _write(tmp_path, "app.py", "x=1\n"),
        _write(tmp_path, ".coverage", "data"),
        _write(tmp_path, "chats.db", "sqlite"),
        _write(tmp_path, "logs/run.log", "log"),
        _write(tmp_path, "src/__pycache__/app.cpython-312.pyc", b"\x00"),
        _write(tmp_path, ".env", "SECRET=x"),
    ]
    m = rm.collect(tmp_path, files=files)
    hit_paths = {a.path for a in m.tracked_artifacts}
    assert ".coverage" in hit_paths
    assert "chats.db" in hit_paths
    assert "logs/run.log" in hit_paths
    assert "src/__pycache__/app.cpython-312.pyc" in hit_paths
    assert ".env" in hit_paths


def test_env_example_is_not_an_artifact(tmp_path):
    files = [_write(tmp_path, ".env.example", "SECRET=\n"),
             _write(tmp_path, ".env.template", "X=\n")]
    m = rm.collect(tmp_path, files=files)
    assert m.tracked_artifacts == []


# --------------------------------------------------------------------------- gitignore

def test_gitignore_gaps_reported_when_absent(tmp_path):
    """Gaps are reported for what THIS tree could actually produce.

    This used to assert `node_modules` for a fixture holding one .py file — it was pinning
    the flat expectation list, which charged every repo for every ecosystem. A pure-Python
    tree with no package.json cannot produce node_modules, and docking it for that is not
    a stricter standard, just a wrong one.
    """
    files = [_write(tmp_path, "a.py", "x=1\n")]
    m = rm.collect(tmp_path, files=files)
    assert m.gitignore_present is False
    assert "__pycache__" in m.gitignore_gaps, "there is Python here; caches are real"
    assert ".env" in m.gitignore_gaps, "secrets can leak from any repo"
    assert "node_modules" not in m.gitignore_gaps, "no package.json in this tree"


def test_gitignore_gaps_shrink_when_covered(tmp_path):
    """Declared fragments stop being gaps. `dist` is still expected because the fixture
    carries a pyproject.toml, which is what makes a build output possible at all."""
    _write(tmp_path, ".gitignore", "__pycache__/\nnode_modules/\n.env\n*.log\n")
    files = [
        _write(tmp_path, "a.py", "x=1\n"),
        _write(tmp_path, "pyproject.toml", "[project]\nname = 'x'\n"),
    ]
    m = rm.collect(tmp_path, files=files)
    assert m.gitignore_present is True
    assert "__pycache__" not in m.gitignore_gaps
    assert ".env" not in m.gitignore_gaps
    assert "*.log" not in m.gitignore_gaps
    # dist/build are buildable here (pyproject.toml) and undeclared -> still gaps
    assert "dist" in m.gitignore_gaps


# --------------------------------------------------------------------------- flags

def test_flag_hits_counted(tmp_path):
    body = "import os\na = os.getenv('A')\nb = os.getenv('B')\nc = os.environ['C']\n"
    files = [_write(tmp_path, "cfg.py", body)]
    m = rm.collect(tmp_path, files=files)
    assert m.flag_hit_total == 3  # two getenv + one environ
    assert m.flag_hits[0].path == "cfg.py"


def test_custom_flag_pattern(tmp_path):
    files = [_write(tmp_path, "f.js", "const x = process.env.FOO;\n")]
    m = rm.collect(tmp_path, files=files, flag_patterns=(r"process\.env\.",))
    assert m.flag_hit_total == 1


# --------------------------------------------------------------------------- dead modules

def test_dead_module_candidate_detected(tmp_path):
    _write(tmp_path, "used.py", "def f():\n    return 1\n")
    _write(tmp_path, "orphan.py", "def g():\n    return 2\n")  # never imported
    _write(tmp_path, "main.py", "from used import f\n")
    files = ["used.py", "orphan.py", "main.py"]
    m = rm.collect(tmp_path, files=files)
    assert "orphan.py" in m.dead_module_candidates
    assert "used.py" not in m.dead_module_candidates  # imported by main


def test_dead_module_excludes_entrypoints_and_tests(tmp_path):
    _write(tmp_path, "cli.py", "if __name__ == '__main__':\n    print('go')\n")  # runnable
    _write(tmp_path, "__init__.py", "")
    _write(tmp_path, "tests/test_x.py", "def test_x():\n    assert True\n")
    files = ["cli.py", "__init__.py", "tests/test_x.py"]
    m = rm.collect(tmp_path, files=files)
    assert m.dead_module_candidates == []


# --------------------------------------------------------------------------- scoring

def test_clean_repo_scores_high(tmp_path):
    _write(tmp_path, ".gitignore",
           "__pycache__/\nnode_modules/\n.coverage\nhtmlcov/\ndist/\nbuild/\n.env\n*.log\n")
    files = [
        _write(tmp_path, "main.py", "from used import f\n"),
        _write(tmp_path, "used.py", "def f():\n    return 1\n"),
    ]
    files.append(".gitignore")
    m = rm.collect(tmp_path, files=files)
    assert m.anchor_score >= 95
    assert m.score_breakdown.final == m.anchor_score


def test_penalties_are_itemised_and_bounded(tmp_path):
    # one God file (600 lines), one tracked artifact, no gitignore
    big = "\n".join(f"l{i}" for i in range(600)) + "\n"
    files = [
        _write(tmp_path, "god.py", big),
        _write(tmp_path, ".coverage", "x"),
    ]
    m = rm.collect(tmp_path, files=files)
    b = m.score_breakdown
    assert b.god_file_penalty > 0
    assert b.artifact_penalty == 3          # one artifact * 3
    assert b.gitignore_gap_penalty > 0      # no .gitignore at all
    assert b.final == 100 - b.god_file_penalty - b.artifact_penalty \
        - b.gitignore_gap_penalty - b.large_file_penalty - b.dead_candidate_penalty


def test_score_never_below_zero(tmp_path):
    # pile on many artifacts and god files; score must clamp at 0, not go negative
    files = []
    for i in range(40):
        files.append(_write(tmp_path, f"logs/f{i}.log", "x"))
    for i in range(20):
        big = "\n".join(str(j) for j in range(2000)) + "\n"
        files.append(_write(tmp_path, f"mod{i}.py", big))
    m = rm.collect(tmp_path, files=files)
    assert 0 <= m.anchor_score <= 100


def test_god_penalty_capped(tmp_path):
    # 50 huge god files must not push the god penalty past its cap of 40
    files = []
    for i in range(50):
        big = "\n".join(str(j) for j in range(3000)) + "\n"
        files.append(_write(tmp_path, f"m{i}.py", big))
    m = rm.collect(tmp_path, files=files)
    assert m.score_breakdown.god_file_penalty == 40


# --------------------------------------------------------------------------- determinism

def test_determinism_same_input_same_output(tmp_path):
    _write(tmp_path, "a.py", "import os\nos.getenv('X')\n")
    _write(tmp_path, "b.py", "\n".join(str(i) for i in range(700)) + "\n")
    _write(tmp_path, ".coverage", "x")
    files = ["a.py", "b.py", ".coverage"]
    r1 = rm.collect(tmp_path, files=files).to_json()
    r2 = rm.collect(tmp_path, files=files).to_json()
    assert r1 == r2
    # and stable across a reordered input list (we sort internally)
    r3 = rm.collect(tmp_path, files=list(reversed(files))).to_json()
    assert r1 == r3


def test_largest_files_sorted_and_capped(tmp_path):
    files = []
    for i in range(20):
        files.append(_write(tmp_path, f"big{i}.bin", b"\x00" * (LARGE := 1_100_000 + i)))
    m = rm.collect(tmp_path, files=files, largest_n=5)
    assert len(m.largest_files) == 5
    sizes = [f.bytes for f in m.largest_files]
    assert sizes == sorted(sizes, reverse=True)


# --------------------------------------------------------------------------- CLI / json

def test_to_json_is_valid_and_roundtrips(tmp_path):
    files = [_write(tmp_path, "a.py", "x=1\n")]
    m = rm.collect(tmp_path, files=files)
    parsed = json.loads(m.to_json())
    assert parsed["file_count"] == 1
    assert parsed["anchor_score"] == m.anchor_score
    assert "score_breakdown" in parsed


def test_main_emits_json(tmp_path, capsys):
    _write(tmp_path, "a.py", "x=1\n")
    # not a git repo -> falls back to walk; should still run and emit valid json
    rc = rm.main([str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["file_count"] >= 1
    assert any("not a git repo" in n for n in parsed["notes"])


# --------------------------------------------------------------------------- metric accuracy
#
# Both fixes below were prompted by the same failure: the anchor score reported 42/100 for
# this repo with 18 of 58 penalty points coming from findings that were simply wrong. A
# score that is wrong for reasons the reader can check is worse than no score, because the
# reader stops trusting the parts that were right.


def test_from_import_records_the_imported_names_not_just_the_package():
    """`from harness import runner, scoring` must mark runner and scoring as referenced.

    Matching only the path after `from` missed the most ordinary way there is to import a
    submodule, so a package's own modules were reported dead while being imported on the
    next line. All six of this repo's candidates were live.
    """
    src = "from harness import runner, scoring\n"
    dead = rm._python_dead_module_candidates([
        ("pkg/user.py", _tmp_py(src)),
        ("pkg/runner.py", _tmp_py("X = 1\n")),
        ("pkg/scoring.py", _tmp_py("Y = 2\n")),
    ])
    # user.py itself is unreferenced and correctly flagged; the claim is about the two
    # modules it imports, so assert on those rather than on an empty list.
    assert "pkg/runner.py" not in dead
    assert "pkg/scoring.py" not in dead


def test_bare_import_is_recorded():
    r"""`\s` inside a character class matches newlines, so a naive `[\w.,\s]+` swallows
    the following lines and breaks every bare `import x`."""
    dead = rm._python_dead_module_candidates([
        ("pkg/user.py", _tmp_py("import loop_common\n\nfrom pathlib import Path\n")),
        ("pkg/loop_common.py", _tmp_py("X = 1\n")),
    ])
    assert "pkg/loop_common.py" not in dead


def test_import_with_a_trailing_comment_is_recorded():
    """`import fixtures  # noqa: E402` is ordinary in this repo (sys.path juggling)."""
    dead = rm._python_dead_module_candidates([
        ("pkg/user.py", _tmp_py("import fixtures  # noqa: E402\n")),
        ("pkg/fixtures.py", _tmp_py("X = 1\n")),
    ])
    assert "pkg/fixtures.py" not in dead


def test_import_aliased_records_the_real_module():
    dead = rm._python_dead_module_candidates([
        ("pkg/user.py", _tmp_py("import baseline as bl\nfrom . import db, nl\n")),
        ("pkg/baseline.py", _tmp_py("X = 1\n")),
        ("pkg/db.py", _tmp_py("Y = 2\n")),
        ("pkg/nl.py", _tmp_py("Z = 3\n")),
    ])
    assert not {"pkg/baseline.py", "pkg/db.py", "pkg/nl.py"} & set(dead)


def test_a_genuinely_unreferenced_module_is_still_reported():
    """The counterpart guard: fixing the false positives must not blunt the check."""
    dead = rm._python_dead_module_candidates([
        ("pkg/user.py", _tmp_py("import something_else\n")),
        ("pkg/orphan.py", _tmp_py("X = 1\n")),
    ])
    assert "pkg/orphan.py" in dead


def test_gitignore_gaps_skip_ecosystems_the_repo_does_not_have(tmp_path):
    """A pure-Python repo with no build step was docked for not ignoring node_modules."""
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    files = ["main.py", "conftest.py"]

    present, gaps = rm._gitignore_gaps(tmp_path, files)

    assert present
    assert "node_modules" not in gaps, "no package.json — node_modules cannot occur here"
    assert "dist" not in gaps and "build" not in gaps, "no build config in this tree"
    assert ".env" in gaps and "*.log" in gaps, "secrets and logs can appear in any repo"


def test_gitignore_gaps_include_an_ecosystem_the_repo_does_have(tmp_path):
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    files = ["main.py", "package.json"]

    _present, gaps = rm._gitignore_gaps(tmp_path, files)

    assert "node_modules" in gaps, "package.json present — node_modules is a real risk"


def test_gitignore_gaps_without_a_file_list_keeps_the_old_behaviour(tmp_path):
    """Callers that pass no file list still get the full expectation set."""
    (tmp_path / ".gitignore").write_text("nothing\n", encoding="utf-8")
    _present, gaps = rm._gitignore_gaps(tmp_path)
    assert set(gaps) == set(rm.GITIGNORE_EXPECTED)


def test_gitignore_expected_is_derived_from_the_rules():
    """The compatibility alias must not drift from the table it mirrors."""
    assert rm.GITIGNORE_EXPECTED == tuple(f for f, _ in rm.GITIGNORE_RULES)


def test_dotenv_is_not_hidden_by_a_venv_line(tmp_path):
    """The false negative that hid a credential-publishing gap in every Python repo.

    `.env` normalises to the needle `env`, and `.venv` contains `env`, so a substring test
    reported `.env` as covered in any repo using a virtualenv. That is the worst possible
    place for this check to be wrong: it hides the one entry whose absence can publish a
    key, and it hides it in the most common possible repo shape. Found only by a full audit.
    """
    _write(tmp_path, ".gitignore", "__pycache__/\n.venv/\n")
    files = ["main.py", "conftest.py"]

    _present, gaps = rm._gitignore_gaps(tmp_path, files)

    assert ".env" in gaps, "a .venv line must not be read as covering .env"


def test_dotenv_is_cleared_when_actually_declared(tmp_path):
    """The counterpart: fixing the false negative must not create a false positive."""
    _write(tmp_path, ".gitignore", "__pycache__/\n.venv/\n.env\n.env.*\n!.env.example\n")
    _present, gaps = rm._gitignore_gaps(tmp_path, ["main.py"])
    assert ".env" not in gaps


def test_a_negation_entry_is_not_coverage():
    """`!.env.example` re-includes a file; it does not ignore anything."""
    assert rm._covered_by(".env", {"!.env.example"}) is False
    assert rm._covered_by(".env", {".env"}) is True


def test_wildcard_entries_still_count_as_coverage():
    assert rm._covered_by(".env", {".env*"}) is True
    assert rm._covered_by("*.log", {"logs/*.log"}) is True
    assert rm._covered_by("dist", {"dist"}) is True


def test_a_merely_similar_entry_does_not_count():
    """The general form of the .venv/.env bug — no substring shortcuts."""
    assert rm._covered_by(".env", {".venv"}) is False
    assert rm._covered_by("build", {"rebuilder"}) is False
    assert rm._covered_by("dist", {"distribution_notes.md"}) is False
