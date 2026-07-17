"""Tests for scripts/validate_manifests.py. Pure stdlib; headless."""
from __future__ import annotations

import json
from pathlib import Path

import validate_manifests as vm

REPO_ROOT = Path(__file__).resolve().parent.parent


def _make_repo(tmp_path, *, plugin_name="foo", version="0.1.0", with_desc=True,
               source="./plugins/foo", entry_name=None) -> Path:
    """Build a minimal valid marketplace+plugin, tweakable for negative cases."""
    root = tmp_path
    pdir = root / "plugins" / "foo" / ".claude-plugin"
    pdir.mkdir(parents=True)
    manifest = {"name": plugin_name, "version": version}
    if with_desc:
        manifest["description"] = "a plugin"
    (pdir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    mkt = root / ".claude-plugin"
    mkt.mkdir(parents=True)
    (mkt / "marketplace.json").write_text(json.dumps({
        "name": "m", "plugins": [{"name": entry_name or plugin_name, "source": source,
                                  "description": "x"}]
    }), encoding="utf-8")
    return root


# --------------------------------------------------------------------------- happy path
def test_minimal_repo_validates(tmp_path):
    assert vm.validate(_make_repo(tmp_path)) == []


def test_real_repo_manifests_are_valid():
    problems = vm.validate(REPO_ROOT)
    assert problems == [], "real repo manifests should validate:\n" + "\n".join(problems)


# --------------------------------------------------------------------------- negative cases
def test_bad_version_flagged(tmp_path):
    problems = vm.validate(_make_repo(tmp_path, version="1.0"))
    assert any("semver" in p for p in problems)


def test_missing_description_flagged(tmp_path):
    problems = vm.validate(_make_repo(tmp_path, with_desc=False))
    assert any("description" in p for p in problems)


def test_missing_source_dir_flagged(tmp_path):
    problems = vm.validate(_make_repo(tmp_path, source="./plugins/does-not-exist"))
    assert any("not a directory" in p for p in problems)


def test_name_mismatch_flagged(tmp_path):
    # marketplace entry says 'bar' but the plugin manifest says 'foo'
    problems = vm.validate(_make_repo(tmp_path, plugin_name="foo", entry_name="bar"))
    assert any("!= manifest name" in p for p in problems)


def test_invalid_json_flagged(tmp_path):
    root = _make_repo(tmp_path)
    (root / "plugins" / "foo" / ".claude-plugin" / "plugin.json").write_text("{not json", encoding="utf-8")
    problems = vm.validate(root)
    assert any("invalid JSON" in p for p in problems)


def test_no_plugins_dir(tmp_path):
    problems = vm.validate(tmp_path)
    assert any("no plugins/" in p for p in problems)


def test_main_returns_nonzero_on_bad_repo(tmp_path):
    root = _make_repo(tmp_path, version="nope")
    assert vm.main([str(root)]) == 1


def test_main_returns_zero_on_real_repo():
    assert vm.main([str(REPO_ROOT)]) == 0
