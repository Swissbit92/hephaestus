"""Tests for the cross-agent skill installer.

Claude Code consumes this repo as plugins. Codex and Pi have no plugin container — they
discover skill directories — so the portable subset is exactly the skills, and commands,
subagents, hooks and MCP servers do not travel.

The property worth protecting is that the asymmetry stays *stated*. A skill that silently
loses its hook in one agent is worse than one that fails to load: it appears to work while
the guarantee the hook provided is absent. So the installer prints what will not travel,
and `test_reports_what_cannot_travel` fails if it stops.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "install_skills.py"


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _fake_marketplace(root: Path) -> Path:
    plug = root / "plugins" / "demo"
    (plug / "skills" / "alpha").mkdir(parents=True)
    (plug / "skills" / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: does a thing and says when.\n---\n\nbody\n",
        encoding="utf-8")
    (plug / "skills" / "beta").mkdir(parents=True)
    (plug / "skills" / "beta" / "SKILL.md").write_text(
        "---\nname: beta\ndescription: does another thing and says when.\n---\n\nbody\n",
        encoding="utf-8")
    (plug / ".claude-plugin").mkdir(parents=True)
    (plug / ".claude-plugin" / "plugin.json").write_text(
        '{"name":"demo","version":"0.1.0","description":"d","hooks":{}}', encoding="utf-8")
    (plug / "commands").mkdir()
    (plug / "commands" / "go.md").write_text("x", encoding="utf-8")
    return root


# --- the default is to change nothing ------------------------------------------------------

def test_default_is_a_plan_and_writes_nothing(tmp_path):
    repo = _fake_marketplace(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    r = _run("--repo", str(repo), "--home", str(home))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PLAN ONLY" in r.stdout
    assert not list(home.rglob("SKILL.md")), "a plan must not create anything"


def test_apply_installs_every_skill_for_every_agent(tmp_path):
    repo = _fake_marketplace(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    r = _run("--repo", str(repo), "--home", str(home), "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    for agent_dir in (".claude/skills", ".codex/skills", ".pi/agent/skills"):
        for skill in ("alpha", "beta"):
            target = home / agent_dir / skill / "SKILL.md"
            assert target.is_file(), "missing {}".format(target)
            assert "name: {}".format(skill) in target.read_text(encoding="utf-8")


def test_a_single_agent_can_be_targeted(tmp_path):
    repo = _fake_marketplace(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    _run("--repo", str(repo), "--home", str(home), "--agent", "codex", "--apply")
    assert (home / ".codex" / "skills" / "alpha" / "SKILL.md").is_file()
    assert not (home / ".pi").exists()


def test_reinstall_is_idempotent(tmp_path):
    """Installing twice must converge, not fail on the existing entry."""
    repo = _fake_marketplace(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    first = _run("--repo", str(repo), "--home", str(home), "--agent", "pi", "--apply")
    second = _run("--repo", str(repo), "--home", str(home), "--agent", "pi", "--apply")
    assert first.returncode == 0 and second.returncode == 0, second.stdout + second.stderr
    assert (home / ".pi" / "agent" / "skills" / "alpha" / "SKILL.md").is_file()


def test_an_edit_reaches_a_linked_install(tmp_path):
    """One source of truth is the reason to link. Where the platform copies, it says so.

    The assertion is conditional on purpose: on Windows without Developer Mode a symlink
    raises, the installer degrades to a copy, and the honest behaviour there is that the
    copy does *not* track edits — which the output states.
    """
    repo = _fake_marketplace(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    r = _run("--repo", str(repo), "--home", str(home), "--agent", "pi", "--apply")
    installed = home / ".pi" / "agent" / "skills" / "alpha"
    source = repo / "plugins" / "demo" / "skills" / "alpha" / "SKILL.md"
    source.write_text(source.read_text(encoding="utf-8") + "\nedited\n", encoding="utf-8")

    if installed.is_symlink():
        assert "edited" in (installed / "SKILL.md").read_text(encoding="utf-8")
    else:
        assert "COPIED" in r.stdout, "a copy must announce that it will not track updates"


# --- the asymmetry must stay visible ---------------------------------------------------------

def test_reports_what_cannot_travel(tmp_path):
    repo = _fake_marketplace(tmp_path / "repo")
    home = tmp_path / "home"
    home.mkdir()
    r = _run("--repo", str(repo), "--home", str(home), "--report", "--apply")
    assert "NOT portable" in r.stdout
    assert "slash commands" in r.stdout
    assert "hooks" in r.stdout


def test_real_marketplace_reports_cruciblesown_gaps():
    """Against this repo: crucible really does ship commands, subagents and hooks."""
    r = _run("--repo", str(REPO_ROOT), "--home", str(REPO_ROOT / "nonexistent-home"))
    # A missing home is a could-not-determine, so point at a real one for the gap listing.
    r = _run("--repo", str(REPO_ROOT), "--home", str(REPO_ROOT))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "crucible" in r.stdout
    assert "subagents" in r.stdout


# --- exit-code discipline ----------------------------------------------------------------------

def test_no_skills_is_exit_2_not_success(tmp_path):
    empty = tmp_path / "empty"
    (empty / "plugins").mkdir(parents=True)
    r = _run("--repo", str(empty), "--home", str(tmp_path))
    assert r.returncode == 2, r.stdout + r.stderr


def test_missing_home_is_exit_2(tmp_path):
    repo = _fake_marketplace(tmp_path / "repo")
    r = _run("--repo", str(repo), "--home", str(tmp_path / "nope"))
    assert r.returncode == 2
