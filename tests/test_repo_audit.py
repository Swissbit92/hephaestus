"""Tests for the repo-audit deterministic metrics (repo_metrics.py).

The whole reason this script exists is *reproducibility* — so these tests pin the exact
facts and the exact score arithmetic, and prove determinism (same input -> same output).
Pure stdlib; headless. Hermetic: every test passes an explicit `files` list so nothing
depends on git or the real tree.
"""
from __future__ import annotations

import json

import repo_metrics as rm


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
    files = [_write(tmp_path, "a.py", "x=1\n")]
    m = rm.collect(tmp_path, files=files)
    assert m.gitignore_present is False
    assert "node_modules" in m.gitignore_gaps
    assert "__pycache__" in m.gitignore_gaps


def test_gitignore_gaps_shrink_when_covered(tmp_path):
    _write(tmp_path, ".gitignore", "__pycache__/\nnode_modules/\n.env\n*.log\n")
    files = [_write(tmp_path, "a.py", "x=1\n")]
    m = rm.collect(tmp_path, files=files)
    assert m.gitignore_present is True
    assert "__pycache__" not in m.gitignore_gaps
    assert "node_modules" not in m.gitignore_gaps
    assert ".env" not in m.gitignore_gaps
    assert "*.log" not in m.gitignore_gaps
    # dist/build still not declared -> still gaps
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
