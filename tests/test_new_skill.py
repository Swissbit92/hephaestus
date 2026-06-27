"""Tests for the skill scaffolder (scripts/new_skill.py)."""
from __future__ import annotations

import pytest

import new_skill


def test_create_skill_writes_stub(tmp_path):
    path = new_skill.create_skill(tmp_path, "my-skill", "does a thing")
    assert path.exists()
    assert path == tmp_path / "my-skill" / "SKILL.md"
    text = path.read_text()
    assert "name: my-skill" in text
    assert "description: does a thing" in text


def test_stub_embeds_the_patterns(tmp_path):
    text = new_skill.create_skill(tmp_path, "s", "d").read_text()
    # The stub should guide toward the high-leverage patterns, not be blank boilerplate.
    for marker in ["Do-not", "BAD", "GOOD", "HARD GATE", "Output", "Guardrails",
                   "CLAUDE_SKILL_DIR", "progressive disclosure"]:
        assert marker in text, f"stub missing pattern marker: {marker}"


@pytest.mark.parametrize("name", ["my-skill", "skill1", "a", "a-b-c"])
def test_valid_names(name):
    assert new_skill.valid_name(name)


@pytest.mark.parametrize("name", ["My-Skill", "skill_name", "-x", "x-", "a--b", "", "x y"])
def test_invalid_names_rejected(tmp_path, name):
    assert not new_skill.valid_name(name)
    with pytest.raises(ValueError):
        new_skill.create_skill(tmp_path, name, "d")


def test_refuses_existing_without_force(tmp_path):
    new_skill.create_skill(tmp_path, "dup", "d")
    with pytest.raises(FileExistsError):
        new_skill.create_skill(tmp_path, "dup", "d")


def test_force_overwrites(tmp_path):
    new_skill.create_skill(tmp_path, "dup", "first")
    path = new_skill.create_skill(tmp_path, "dup", "second", force=True)
    assert "description: second" in path.read_text()


def test_default_skills_dir_points_at_whetstone_plugin():
    # Sanity: the default lands inside the whetstone plugin's skills/ dir, and exists.
    assert new_skill._DEFAULT_SKILLS_DIR.name == "skills"
    assert new_skill._DEFAULT_SKILLS_DIR.parent.name == "whetstone"
    assert new_skill._DEFAULT_SKILLS_DIR.exists()


def test_main_invalid_name_returns_1():
    assert new_skill.main(["bad name"]) == 1


def test_main_creates_skill(tmp_path):
    rc = new_skill.main(["good-name", "--skills-dir", str(tmp_path), "--description", "x"])
    assert rc == 0
    assert (tmp_path / "good-name" / "SKILL.md").exists()
