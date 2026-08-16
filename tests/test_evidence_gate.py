"""Tests for the declarable evidence gate.

The defect this closes is not hypothetical. `finish-branch` gated on "tests green, no
regression against the branch point". Pointed at a repository with no test assemblies —
a Unity game, in the case that motivated it — that sentence has no referent, so the gate
reported success because nothing had failed. "Nothing failed" and "it works" are different
claims, and only one of them was being checked.

The fixtures below use the shape of that project's own evidence table (netcode needs a
two-peer traced run; anything visual needs an image captured on the peer that should see
it; docs need nothing) because an invented one would not have the property that matters:
different classes, triggered by different paths, with genuinely different costs.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugins" / "crucible" / "scripts" / "evidence_gate.py"

DECLARATION = {
    "classes": [
        {"when": "netcode, prediction or networked state",
         "evidence": "a two-peer traced run; input-driven transitions carry the same tick "
                     "on both peers",
         "paths": ["src/net/*", "src/net/**"]},
        {"when": "anything visual",
         "evidence": "a run with an image, captured on the peer that should see it",
         "paths": ["assets/*"]},
        {"when": "documentation",
         "evidence": "none beyond the document checks",
         "paths": ["docs/*"]},
    ]
}


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _declare(root: Path, payload) -> Path:
    d = root / ".crucible"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "evidence.json"
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                 encoding="utf-8")
    return p


# --- resolution order -------------------------------------------------------------------

def test_declaration_is_reported(tmp_path):
    _declare(tmp_path, DECLARATION)
    r = _run("--repo", str(tmp_path), "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["source"] == "declared"
    assert len(out["classes"]) == 3
    assert "two-peer" in out["classes"][0]["evidence"]


def test_a_repo_with_test_gates_and_no_declaration_still_works(tmp_path):
    """Backward compatibility is the whole reason the implied class exists.

    Every repository that gated on tests before this change must keep gating on tests
    without editing anything.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    r = _run("--repo", str(tmp_path), "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["source"] == "implied"
    assert "test gates" in out["classes"][0]["evidence"]


def test_declaration_wins_over_detected_gates(tmp_path):
    """A repo that has tests *and* an opinion gets its opinion, not the default."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntestpaths = ['tests']\n", encoding="utf-8")
    _declare(tmp_path, DECLARATION)
    out = json.loads(_run("--repo", str(tmp_path), "--json").stdout)
    assert out["source"] == "declared"


# --- the exit-code discipline this repo treats as an invariant ---------------------------

def test_nothing_to_gate_is_exit_3_not_a_pass(tmp_path):
    """No declaration and no gates must not read as success."""
    r = _run("--repo", str(tmp_path))
    assert r.returncode == 3, r.stdout + r.stderr
    assert "nothing to gate" in (r.stdout + r.stderr)


def test_malformed_declaration_is_exit_2_not_a_fallback(tmp_path):
    """A present-but-broken declaration must never silently degrade to the default.

    This is the case where guessing is worst: the repository has stated a requirement, and
    falling back would replace it with a weaker one while reporting success.
    """
    _declare(tmp_path, "{not json at all")
    r = _run("--repo", str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr
    assert "not valid JSON" in r.stderr


def test_empty_classes_list_is_malformed(tmp_path):
    _declare(tmp_path, {"classes": []})
    assert _run("--repo", str(tmp_path)).returncode == 2


def test_class_without_evidence_is_malformed(tmp_path):
    _declare(tmp_path, {"classes": [{"when": "anything"}]})
    r = _run("--repo", str(tmp_path))
    assert r.returncode == 2
    assert "evidence" in r.stderr


def test_paths_must_be_globs(tmp_path):
    _declare(tmp_path, {"classes": [{"when": "x", "evidence": "y", "paths": "src/*"}]})
    assert _run("--repo", str(tmp_path)).returncode == 2


def test_missing_repo_is_exit_2(tmp_path):
    assert _run("--repo", str(tmp_path / "nope")).returncode == 2


# --- narrowing to a diff ------------------------------------------------------------------

def _git_repo(root: Path) -> None:
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], capture_output=True,
                                    text=True, encoding="utf-8", errors="replace")
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.invalid")
    run("config", "user.name", "T")
    run("config", "commit.gpgsign", "false")


def test_diff_narrows_to_the_classes_a_change_triggers(tmp_path):
    _git_repo(tmp_path)
    _declare(tmp_path, DECLARATION)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"],
                   capture_output=True)
    (tmp_path / "docs" / "b.md").write_text("y", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "docs only"],
                   capture_output=True)

    out = json.loads(_run("--repo", str(tmp_path), "--base", "main~1", "--json").stdout)
    whens = [c["when"] for c in out["classes"]]
    assert whens == ["documentation"], whens


def test_uncommitted_and_untracked_work_is_in_the_diff(tmp_path):
    """A brand-new file is the case most likely to introduce a new evidence class.

    `git diff <base>...HEAD` sees committed state only, so an untracked file is invisible to
    it — and narrowing it away would report a satisfied contract while skipping the work in
    progress. Found by adding this repository's own declaration and watching the gate say
    "0 files changed" with a new file sitting right there.
    """
    _git_repo(tmp_path)
    _declare(tmp_path, DECLARATION)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], capture_output=True)

    # Untracked, never committed, and it belongs to a class the committed diff cannot see.
    (tmp_path / "src" / "net").mkdir(parents=True)
    (tmp_path / "src" / "net" / "peer.py").write_text("x", encoding="utf-8")

    out = json.loads(_run("--repo", str(tmp_path), "--base", "HEAD", "--json").stdout)
    assert "src/net/peer.py" in out["changed_files"], out["changed_files"]
    assert [c["when"] for c in out["classes"]] == ["netcode, prediction or networked state"]


def test_an_unresolvable_base_is_exit_2_not_an_empty_diff(tmp_path):
    """Regression, and the sharpest one in this script's history.

    `changed_files` swallowed a git failure and returned `[]`. The caller read that as "no
    files changed", narrowed every path-scoped class away, and reported a satisfied
    contract derived from a diff that was never taken. Found by running the gate on this
    repo's own branch against `dev`, which exists only as `origin/dev` on a fresh clone —
    so the failure mode is the *default* one, not an exotic case.
    """
    _git_repo(tmp_path)
    _declare(tmp_path, DECLARATION)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "render.py").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], capture_output=True)

    r = _run("--repo", str(tmp_path), "--base", "no-such-branch")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "cannot diff" in r.stderr
    assert "refusing to report" in r.stderr


def test_a_genuinely_empty_diff_is_still_a_pass(tmp_path):
    """The fix must not turn 'nothing changed' into an error — only 'could not tell'."""
    _git_repo(tmp_path)
    _declare(tmp_path, DECLARATION)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "base"], capture_output=True)

    r = _run("--repo", str(tmp_path), "--base", "HEAD", "--json")
    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["changed_files"] == []


def test_an_unscoped_class_always_applies():
    """Narrowing is opt-in: a class with no paths demands evidence for every change.

    The safe direction. A declaration that forgets to scope a class asks for *more*
    evidence, never less.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("evidence_gate", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.applies({"when": "w", "evidence": "e"}, ["anything/at/all.txt"]) is True
    assert mod.applies({"when": "w", "evidence": "e", "paths": ["src/*"]},
                       ["docs/a.md"]) is False


# --- the verdict vocabulary ----------------------------------------------------------------

def test_three_verdicts_are_offered_not_two(tmp_path):
    """pass / fail / could-not-check. The third is the point of the whole change."""
    _declare(tmp_path, DECLARATION)
    out = json.loads(_run("--repo", str(tmp_path), "--json").stdout)
    assert out["verdicts"] == ["pass", "fail", "could-not-check"]


def test_human_output_names_the_third_verdict(tmp_path):
    _declare(tmp_path, DECLARATION)
    r = _run("--repo", str(tmp_path))
    assert "could-not-check" in r.stdout
    assert "never be written as 'pass'" in r.stdout
