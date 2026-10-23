"""Tests for the baseline-relative delta gate (metric_delta.py): duplicated code and lint.

The gate compares the SET of finding identities at the branch point with the set now. The
two regressions it exists to prevent are the two simpler gates it replaced: an absolute
gate that fails forever on inherited findings, and a count gate that cannot see one
finding swapped for another. Both are pinned here, plus the could-not-determine paths.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugins" / "crucible" / "scripts" / "metric_delta.py"

sys.path.insert(0, str(REPO_ROOT / "evals"))
import fixtures  # noqa: E402


def _load():
    spec = importlib.util.spec_from_file_location("metric_delta", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


md = _load()

# A fake ruff: one finding "X1" per line containing BAD, in ruff's JSON shape. Real ruff is
# not a test dependency; what is under test is the identity arithmetic, not ruff.
FAKE_RUFF = r'''
import json, sys
from pathlib import Path
out = []
for f in sorted(Path(".").rglob("*.py")):
    for n, line in enumerate(f.read_text().splitlines(), 1):
        if "BAD" in line:
            out.append({"code": "X1", "filename": str(f.resolve()), "message": "bad",
                        "location": {"row": n, "column": 1}})
print(json.dumps(out))
'''


def _run(repo, *args):
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=300)
    return r.returncode, r.stdout + r.stderr


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path, files: dict[str, str]) -> Path:
    return fixtures.branched_repo(tmp_path / "r", files)


def _ruff_args(tmp_path):
    fake = tmp_path / "fake_ruff.py"
    fake.write_text(FAKE_RUFF, encoding="utf-8")
    return ["--metric", "ruff", "--ruff", f"{Path(sys.executable).as_posix()} {fake.as_posix()}"]


# --------------------------------------------------------------------------- clones
def test_a_pasted_function_is_new_duplication(tmp_path):
    repo = fixtures.build("develop_pasted_function", tmp_path / "r")
    code, out = _run(repo, "--metric", "clones")
    assert code == 1, out
    assert "receipt.py:1-7" in out and "also at invoice.py:1" in out


def test_duplication_that_already_existed_is_not_new(tmp_path):
    """Inherited duplication is the base's, not this branch's — the absolute-gate trap."""
    body = fixtures._DUPLICATED
    repo = _repo(tmp_path, {"a.py": body, "b.py": body.replace("render_invoice", "r2")})
    fixtures._write(repo, "c.py", "def unrelated():\n    return 1\n")
    fixtures._commit_all(repo, "unrelated change")
    assert _run(repo, "--metric", "clones")[0] == 0


def test_a_paste_into_an_untracked_file_counts(tmp_path):
    repo = _repo(tmp_path, {"a.py": fixtures._DUPLICATED})
    fixtures._write(repo, "copy.py", fixtures._DUPLICATED.replace("render_invoice", "again"))
    code, out = _run(repo, "--metric", "clones")
    assert code == 1 and "copy.py" in out


def test_comments_do_not_make_code_look_duplicated(tmp_path):
    comment = "".join(f"# the same long comment line number {i}\n" for i in range(40))
    repo = _repo(tmp_path, {"a.py": comment + "x = 1\n"})
    fixtures._write(repo, "b.py", comment + "y = 2\n")
    assert _run(repo, "--metric", "clones")[0] == 0


def test_strip_comments_keeps_strings_and_line_numbers():
    src = 's = "# not a comment"  # a real comment\nt = 1\n'
    assert md.strip_comments(src, ".py") == 's = "# not a comment"  \nt = 1\n'
    js = "a = '//x'; /* one\ntwo */ b = 2 // tail\n"
    out = md.strip_comments(js, ".js")
    assert "'//x'" in out and "tail" not in out and out.count("\n") == 2


def test_exit_3_when_there_is_no_source_to_measure(tmp_path):
    repo = _repo(tmp_path, {"README.md": "# hi\n"})
    code, out = _run(repo, "--metric", "clones")
    assert code == 3 and "SKIP" in out


# --------------------------------------------------------------------------- ruff
def test_an_inherited_lint_finding_is_not_new(tmp_path):
    repo = _repo(tmp_path, {"a.py": "x = 'BAD'\n"})
    fixtures._write(repo, "b.py", "y = 1\n")
    fixtures._commit_all(repo, "clean change")
    code, out = _run(repo, *_ruff_args(tmp_path))
    assert code == 0, out


def test_a_swapped_finding_is_caught_although_the_count_is_unchanged(tmp_path):
    """Fix one, add another: a count gate says nothing changed. The set says otherwise."""
    repo = _repo(tmp_path, {"a.py": "x = 'BAD'\n", "b.py": "y = 1\n"})
    fixtures._write(repo, "a.py", "x = 'ok'\n")
    fixtures._write(repo, "b.py", "y = 'BAD'\n")
    code, out = _run(repo, *_ruff_args(tmp_path))
    assert code == 1 and "b.py:1" in out and "a.py" not in out.split("NEW", 1)[1]


def test_a_finding_that_only_moved_lines_is_not_new(tmp_path):
    repo = _repo(tmp_path, {"a.py": "x = 'BAD'\n"})
    fixtures._write(repo, "a.py", "import os\n\n\nx = 'BAD'\n")
    assert _run(repo, *_ruff_args(tmp_path))[0] == 0


def test_the_base_worktree_is_removed_and_the_tree_untouched(tmp_path):
    repo = _repo(tmp_path, {"a.py": "x = 1\n"})
    fixtures._write(repo, "a.py", "x = 'BAD'\n")
    before = (repo / "a.py").read_bytes()
    _run(repo, *_ruff_args(tmp_path))
    assert (repo / "a.py").read_bytes() == before
    wts = subprocess.run(["git", "-C", str(repo), "worktree", "list"], capture_output=True,
                         text=True, encoding="utf-8").stdout.strip().splitlines()
    assert len(wts) == 1


def test_exit_2_when_ruff_cannot_run(tmp_path):
    repo = _repo(tmp_path, {"a.py": "x = 1\n"})
    code, out = _run(repo, "--metric", "ruff", "--ruff", "definitely-not-a-ruff-binary")
    assert code == 2 and "cannot determine" in out


# --------------------------------------------------------------------------- could not determine
def test_exit_2_without_an_integration_branch(tmp_path):
    repo = tmp_path / "r"
    fixtures._init(repo)
    fixtures._write(repo, "a.py", "x = 1\n")
    fixtures._commit_all(repo, "only main")
    _git(repo, "branch", "-m", "trunkless")
    code, out = _run(repo, "--metric", "clones")
    assert code == 2 and "no integration branch" in out


def test_exit_2_outside_a_git_repository(tmp_path):
    code, out = _run(tmp_path, "--metric", "clones")
    assert code == 2 and "not a git repository" in out


def test_json_output_lists_the_new_regions(tmp_path):
    repo = fixtures.build("develop_pasted_function", tmp_path / "r")
    code, out = _run(repo, "--metric", "clones", "--json")
    data = json.loads(out)
    assert code == 1 and data["new"][0]["path"] == "receipt.py"
