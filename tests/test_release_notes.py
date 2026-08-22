"""Release-note scoping in `scripts/release.sh`.

The notes used to be filtered to `plugins/<name>/`, which cannot see the work a plugin
release routinely lands elsewhere — a gate in `scripts/`, its tests in `tests/`, an ADR or
research note in `docs/`. Measured across the three releases before the fix: **5 of 11
non-merge commits were dropped**, including an invariant living entirely in `scripts/` and
a spike living entirely in `docs/`. The notes never looked wrong, only short, which is why
it survived three releases.

The fix inverts the scope — everything EXCEPT sibling plugins — so the property the old
filter was actually buying is kept: releasing one plugin must not narrate another's work.
Both halves are asserted here, because widening the scope without the exclusion would
trade under-reporting for cross-contamination, which is worse.

`release.sh` resolves its own repo from `BASH_SOURCE`, so these tests copy it into a
throwaway repository and invoke it for real in `--dry-run` mode rather than re-implementing
its logic — a test that reimplements the thing under test proves only that two copies
agree.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RELEASE_SH = REPO_ROOT / "scripts" / "release.sh"


def _find_bash() -> str | None:
    """A bash that actually RUNS, found by executing candidates rather than by name.

    `shutil.which("bash")` is not evidence on Windows: it resolves to WSL's launcher at
    System32\\bash.exe, which starts, fails with `execvpe /bin/bash failed`, and cannot be
    told apart from Git Bash by name alone. This is the same defect the repo already
    documents for `python3` (a Microsoft Store alias that prints an ad and exits 49) and
    the reason `scripts/checks/_python.sh` probes instead of trusting `command -v`.
    """
    candidates = []
    env_bash = os.environ.get("BASH")
    if env_bash:
        candidates.append(env_bash)
    git = shutil.which("git")
    if git:
        # Git for Windows ships bash beside and beneath its own bin/.
        gitdir = Path(git).resolve().parent
        candidates += [str(gitdir / "bash.exe"),
                       str(gitdir.parent / "bin" / "bash.exe"),
                       str(gitdir.parent / "usr" / "bin" / "bash.exe")]
    found = shutil.which("bash")
    if found:
        candidates.append(found)

    for cand in candidates:
        if not cand or not Path(cand).exists():
            continue
        try:
            proc = subprocess.run([cand, "-c", "echo __bash_ok__"], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0 and "__bash_ok__" in proc.stdout:
            return cand
    return None


BASH = _find_bash()

pytestmark = pytest.mark.skipif(BASH is None, reason="no bash that actually runs")


def _git(repo: Path, *args: str, when: str = "2026-01-01T12:00:00+00:00") -> None:
    env = dict(os.environ)
    env["GIT_COMMITTER_DATE"] = when
    env["GIT_AUTHOR_DATE"] = when
    subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=T",
                    "-c", "commit.gpgsign=false", *args],
                   cwd=str(repo), env=env, check=True, stdout=subprocess.PIPE,
                   stderr=subprocess.PIPE, encoding="utf-8", errors="replace")


def _commit(repo: Path, rel: str, body: str, subject: str) -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", "--", rel)
    _git(repo, "commit", "--quiet", "-m", subject)


def _manifest(repo: Path, plugin: str, version: str) -> None:
    d = repo / "plugins" / plugin / ".claude-plugin"
    d.mkdir(parents=True, exist_ok=True)
    (d / "plugin.json").write_text(
        json.dumps({"name": plugin, "description": "x", "version": version}, indent=2) + "\n",
        encoding="utf-8")


@pytest.fixture
def repo(tmp_path):
    """A two-plugin repo on `main` with release.sh copied in, tagged at alpha-v0.1.0."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "--quiet", "--initial-branch=main", ".")

    (r / "scripts" / "checks").mkdir(parents=True)
    shutil.copy(RELEASE_SH, r / "scripts" / "release.sh")
    shutil.copy(REPO_ROOT / "scripts" / "checks" / "_python.sh",
                r / "scripts" / "checks" / "_python.sh")
    shutil.copy(REPO_ROOT / "scripts" / "bump_version.py", r / "scripts" / "bump_version.py")
    _manifest(r, "alpha", "0.1.0")
    _manifest(r, "beta", "0.1.0")
    _git(r, "add", "-A")
    _git(r, "commit", "--quiet", "-m", "initial")
    _git(r, "tag", "-a", "alpha-v0.1.0", "-m", "alpha 0.1.0")
    return r


def _notes(repo: Path, plugin: str, version: str) -> str:
    proc = subprocess.run(
        [BASH, "scripts/release.sh", plugin, version, "--dry-run"],
        cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


# --------------------------------------------------------------------------- the gap
def test_work_outside_the_plugin_directory_is_reported(repo):
    """The regression: a gate in scripts/ and a note in docs/ used to be invisible."""
    _commit(repo, "scripts/new_gate.py", "x = 1\n", "feat: a gate that lives in scripts")
    _commit(repo, "docs/research/note.md", "# note\n", "docs: a spike that lives in docs")
    _commit(repo, "tests/test_new_gate.py", "def test_x(): pass\n", "test: cover the gate")

    out = _notes(repo, "alpha", "0.2.0")

    assert "a gate that lives in scripts" in out
    assert "a spike that lives in docs" in out
    assert "cover the gate" in out


def test_the_plugins_own_commits_are_still_reported(repo):
    _commit(repo, "plugins/alpha/skills/s/SKILL.md", "x\n", "feat(alpha): a real change")
    out = _notes(repo, "alpha", "0.2.0")
    assert "a real change" in out


# --------------------------------------------------------------------------- the guard
def test_a_sibling_plugins_work_is_not_narrated(repo):
    """Widening the scope without excluding siblings trades under-reporting for
    cross-contamination, which is worse — a release would claim another plugin's work."""
    _commit(repo, "plugins/beta/skills/s/SKILL.md", "x\n", "feat(beta): not alpha's work")
    _commit(repo, "scripts/shared.py", "x = 1\n", "feat: shared tooling")

    out = _notes(repo, "alpha", "0.2.0")

    assert "not alpha's work" not in out, "alpha's release must not narrate beta's commits"
    assert "shared tooling" in out, "but shared tooling is genuinely part of the release"


def test_each_plugin_sees_only_its_own(repo):
    _commit(repo, "plugins/alpha/a.md", "x\n", "feat(alpha): alpha only")
    _commit(repo, "plugins/beta/b.md", "x\n", "feat(beta): beta only")

    alpha_out = _notes(repo, "alpha", "0.2.0")

    assert "alpha only" in alpha_out
    assert "beta only" not in alpha_out


# --------------------------------------------------------------------------- noise
def test_merge_subjects_are_excluded(repo):
    """"Merge pull request #7 from ..." tells a reader nothing about what shipped, and the
    commits it brought in are already in the range."""
    _git(repo, "checkout", "--quiet", "-b", "side")
    _commit(repo, "scripts/side.py", "x = 1\n", "feat: work done on a side branch")
    _git(repo, "checkout", "--quiet", "main")
    _git(repo, "merge", "--no-ff", "--quiet", "side", "-m", "Merge pull request #99 from side")

    out = _notes(repo, "alpha", "0.2.0")

    assert "work done on a side branch" in out, "the merged work must still be reported"
    assert "Merge pull request #99" not in out


def test_trailers_are_stripped(repo):
    _commit(repo, "scripts/x.py", "x = 1\n",
            "feat: a change\n\nCo-Authored-By: Someone <a@b.c>\nClaude-Session: https://x")
    out = _notes(repo, "alpha", "0.2.0")
    assert "a change" in out
    assert "Co-Authored" not in out
    assert "Claude-Session" not in out


def test_no_commits_says_so_rather_than_implying_a_choice(repo):
    """"Maintenance release" reads as deliberate. For three releases it was silently
    covering for a filter that matched nothing."""
    proc = subprocess.run(
        [BASH, "scripts/release.sh", "alpha", "0.2.0", "--dry-run"],
        cwd=str(repo), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180)

    assert proc.returncode == 0
    assert "Maintenance release" in proc.stdout
    assert "no commits found" in proc.stderr, "the empty case must announce itself"


def test_a_commit_touching_both_a_sibling_and_shared_paths_is_included(repo):
    """The mixed case, pinned deliberately — it is a trade-off, not an oversight.

    A commit touching ONLY a sibling plugin is excluded (see the test above). A commit
    touching a sibling AND shared tooling is INCLUDED, because it genuinely did work that
    belongs to this release too, and a pathspec cannot split one commit in half.

    The alternative — dropping any commit that grazes another plugin — is worse: a
    repo-wide refactor touching every plugin would then vanish from every plugin's notes,
    which is the original under-reporting bug wearing a different hat. Over-reporting a
    shared commit costs a reader one line they can evaluate; under-reporting one hides
    work nobody knows to look for.

    Verified against real history when this landed: a forge-unity release would list four
    crucible-era commits, all of which touched `scripts/` or `docs/`. None was pure
    crucible work.
    """
    _commit(repo, "plugins/beta/s.md", "x\n", "feat(beta): pure beta work")
    beta_and_shared = repo / "plugins" / "beta" / "mixed.md"
    beta_and_shared.parent.mkdir(parents=True, exist_ok=True)
    beta_and_shared.write_text("x\n", encoding="utf-8")
    (repo / "scripts" / "shared_tool.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "feat: shared tooling, also touching beta")

    out = _notes(repo, "alpha", "0.2.0")

    assert "pure beta work" not in out, "a commit touching only a sibling stays out"
    assert "shared tooling, also touching beta" in out, "a mixed commit is in, by design"
