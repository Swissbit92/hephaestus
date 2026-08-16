"""Tests for the forge-unity adapter contract and asset-integrity sweep.

The adapter exists because a published plugin cannot ship the commands that matter. The
verbs worth having — start a run, drive input, dump a trace, capture a sheet — are
implemented in a project's own source under names only that project uses. The failure this
must never have is a *plausible guess*: a well-formed command name that runs nothing and is
reported as success. So an unimplemented verb exits 3, and that is asserted here more than
once.

The integrity sweep is the other half: the failures Unity keeps in a parallel record and
never reports. Every fixture below is the shape of a real one — a script with no `.meta`,
a `.meta` whose asset was deleted outside the editor, a component serialised with
`m_Script: {fileID: 0}`. None of them fail a build, a test, or a diff review.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN = REPO_ROOT / "plugins" / "forge-unity"
ADAPTER = PLUGIN / "scripts" / "adapter.py"
INTEGRITY = PLUGIN / "scripts" / "asset_integrity.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


adapter = _load(ADAPTER, "forge_adapter")
integrity = _load(INTEGRITY, "forge_integrity")


def _run(script: Path, *args):
    return subprocess.run([sys.executable, str(script), *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def _declare(root: Path, payload) -> Path:
    d = root / ".forge"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "adapter.json"
    p.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                 encoding="utf-8")
    return p


VALID = {
    "engine": "unity",
    "transport": {"command": "node tools/bridge.mjs exec {verb} {json}"},
    "verbs": {
        "editor.compile": "recompile_scripts",
        "editor.logs": "get_console_logs",
        "capture.sheet": "acme_capture_sheet",
    },
}


# --- the adapter contract ----------------------------------------------------------------

def test_vocabulary_is_engine_neutral():
    """No verb may name a vendor, or a Godot adapter becomes a rewrite rather than a file."""
    joined = " ".join(adapter.VERBS).lower()
    for vendor in ("unity", "godot", "unreal", "photon", "fusion", "mono"):
        assert vendor not in joined, "{!r} leaked into the canonical vocabulary".format(vendor)


def test_resolve_substitutes_the_projects_own_command(tmp_path):
    _declare(tmp_path, VALID)
    r = _run(ADAPTER, "--repo", str(tmp_path), "--resolve", "capture.sheet")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "acme_capture_sheet" in r.stdout
    assert "{verb}" not in r.stdout


def test_unimplemented_verb_is_exit_3_and_never_a_guess(tmp_path):
    """The whole point. A guessed command name runs nothing and reports success."""
    _declare(tmp_path, VALID)
    r = _run(ADAPTER, "--repo", str(tmp_path), "--resolve", "trace.dump")
    assert r.returncode == 3, r.stdout + r.stderr
    assert "does not implement" in r.stderr
    assert not r.stdout.strip(), "nothing may be emitted for a verb that does not exist"


def test_absent_declaration_is_exit_3_not_a_pass(tmp_path):
    r = _run(ADAPTER, "--repo", str(tmp_path))
    assert r.returncode == 3
    assert "forge-init" in r.stderr


def test_malformed_declaration_is_exit_2_not_a_fallback(tmp_path):
    _declare(tmp_path, "{ not json")
    r = _run(ADAPTER, "--repo", str(tmp_path))
    assert r.returncode == 2
    assert "not valid JSON" in r.stderr


def test_transport_without_the_verb_placeholder_is_rejected(tmp_path):
    """Without {verb} every verb runs one command — a failure by doing the wrong thing."""
    broken = json.loads(json.dumps(VALID))
    broken["transport"]["command"] = "node tools/bridge.mjs exec"
    _declare(tmp_path, broken)
    r = _run(ADAPTER, "--repo", str(tmp_path))
    assert r.returncode == 2
    assert "{verb}" in r.stderr


def test_missing_required_verb_is_exit_3(tmp_path):
    thin = json.loads(json.dumps(VALID))
    del thin["verbs"]["editor.compile"]
    _declare(tmp_path, thin)
    r = _run(ADAPTER, "--repo", str(tmp_path))
    assert r.returncode == 3
    assert "editor.compile" in r.stderr


def test_unknown_verb_is_reported_as_drift(tmp_path):
    drifted = json.loads(json.dumps(VALID))
    drifted["verbs"]["editor.compil"] = "typo_here"
    _declare(tmp_path, drifted)
    r = _run(ADAPTER, "--repo", str(tmp_path))
    assert "unknown verb" in r.stderr


def test_payload_is_shell_quoted(tmp_path):
    """A payload reaches a shell, so an unquoted one is an injection, not a bug report."""
    _declare(tmp_path, VALID)
    hostile = '{"a": "b; rm -rf /"}'
    r = _run(ADAPTER, "--repo", str(tmp_path), "--resolve", "editor.compile",
             "--json", hostile)
    assert r.returncode == 0, r.stdout + r.stderr
    line = r.stdout.strip()
    # The whole payload must sit inside one quoted word, so the `;` cannot terminate the
    # command. shlex.quote wraps in single quotes exactly when it needs to.
    assert "'{}'".format(hostile) in line, line


def test_a_json_payload_is_not_mistaken_for_a_placeholder(tmp_path):
    """Regression: the leftover-placeholder check ran after substitution.

    A JSON payload legitimately contains braces, so `{}` in the *data* was read as an
    unfilled `{...}` in the template and a perfectly good adapter was rejected. The
    template is the only thing that can be judged.
    """
    _declare(tmp_path, VALID)
    r = _run(ADAPTER, "--repo", str(tmp_path), "--resolve", "editor.compile", "--json", "{}")
    assert r.returncode == 0, r.stdout + r.stderr


def test_unsupported_placeholder_is_rejected_at_load(tmp_path):
    """Caught by --list too, not only when a verb happens to be resolved."""
    odd = json.loads(json.dumps(VALID))
    odd["transport"]["command"] = "bridge {verb} --project {projectRoot}"
    _declare(tmp_path, odd)
    r = _run(ADAPTER, "--repo", str(tmp_path), "--list")
    assert r.returncode == 2
    assert "{projectRoot}" in r.stderr


def test_vocabulary_listing_needs_no_project():
    r = _run(ADAPTER, "--vocabulary")
    assert r.returncode == 0
    assert "editor.compile" in r.stdout and "[required]" in r.stdout


# --- the asset-integrity sweep -------------------------------------------------------------

def _unity(root: Path) -> Path:
    src = root / "Assets" / "Game"
    (src / "Scripts").mkdir(parents=True)
    (src / "Scenes").mkdir(parents=True)
    return src


def _cs(src: Path, name: str, body: str = "public class {n} : MonoBehaviour {{ }}",
        meta: str = "guid: 0123456789abcdef0123456789abcdef") -> Path:
    p = src / "Scripts" / (name + ".cs")
    p.write_text(body.format(n=name), encoding="utf-8")
    if meta is not None:
        p.with_suffix(".cs.meta").write_text("fileFormatVersion: 2\n" + meta + "\n",
                                             encoding="utf-8")
    return p


def test_source_without_meta_is_found(tmp_path):
    src = _unity(tmp_path)
    _cs(src, "Wired")
    _cs(src, "NeverImported", meta=None)
    found = integrity.run(src)
    assert found["no-meta"] == ["Scripts/NeverImported.cs"]


def test_orphan_meta_is_found(tmp_path):
    src = _unity(tmp_path)
    (src / "Scripts" / "Gone.cs.meta").write_text("guid: aaaa\n", encoding="utf-8")
    found = integrity.run(src)
    assert "Scripts/Gone.cs.meta" in found["orphan-meta"]


def test_broken_script_reference_is_found(tmp_path):
    src = _unity(tmp_path)
    (src / "Scenes" / "Main.unity").write_text(
        "--- !u!114 &1\nMonoBehaviour:\n  m_Script: {fileID: 0}\n", encoding="utf-8")
    found = integrity.run(src)
    assert found["broken-script-ref"] == ["Scenes/Main.unity"]


def test_unwired_only_counts_types_unity_can_attach(tmp_path):
    """An interface or enum is referenced from code and never from a scene.

    Asking whether it appears in a prefab is a category error, and it is not a cheap one:
    on a real project this filter took the list from 29 entries to 1, which is the
    difference between a report someone reads and one they skim.
    """
    src = _unity(tmp_path)
    _cs(src, "LonelyBehaviour")
    _cs(src, "IMoveSource", body="public interface {n} {{ }}")
    _cs(src, "PlayerState", body="public enum {n} {{ Idle, Running }}")
    _cs(src, "GameLayers", body="public static class {n} {{ }}")
    found = integrity.run(src)
    assert found["unwired"] == ["Scripts/LonelyBehaviour.cs"]


def test_a_wired_behaviour_is_not_reported(tmp_path):
    src = _unity(tmp_path)
    _cs(src, "Wired", meta="guid: deadbeefdeadbeefdeadbeefdeadbeef")
    (src / "Scenes" / "Main.unity").write_text(
        "MonoBehaviour:\n  m_Script: {fileID: 11500000, guid: deadbeefdeadbeefdeadbeefdeadbeef}\n",
        encoding="utf-8")
    found = integrity.run(src)
    assert found["unwired"] == []


def test_editor_tooling_is_never_unwired(tmp_path):
    """Editor scripts run from menus; they are never attached to an object."""
    src = _unity(tmp_path)
    (src / "Editor").mkdir()
    p = src / "Editor" / "SetupTool.cs"
    p.write_text("public class SetupTool : MonoBehaviour { }", encoding="utf-8")
    p.with_suffix(".cs.meta").write_text("guid: ffffffffffffffffffffffffffffffff\n",
                                         encoding="utf-8")
    assert integrity.run(src)["unwired"] == []


def test_unwired_is_a_question_and_does_not_fail_the_run(tmp_path):
    """Deleting on this signal alone is how a feature in progress gets removed."""
    src = _unity(tmp_path)
    _cs(src, "LonelyBehaviour")
    r = _run(INTEGRITY, "--root", str(src))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "question" in r.stdout


def test_real_defects_fail_the_run(tmp_path):
    src = _unity(tmp_path)
    _cs(src, "NeverImported", meta=None)
    assert _run(INTEGRITY, "--root", str(src)).returncode == 1


def test_clean_project_passes(tmp_path):
    src = _unity(tmp_path)
    _cs(src, "Wired", meta="guid: deadbeefdeadbeefdeadbeefdeadbeef")
    (src / "Scenes" / "Main.unity").write_text(
        "  m_Script: {fileID: 11500000, guid: deadbeefdeadbeefdeadbeefdeadbeef}\n",
        encoding="utf-8")
    assert _run(INTEGRITY, "--root", str(src)).returncode == 0


def test_missing_root_is_exit_2_not_a_pass(tmp_path):
    assert _run(INTEGRITY, "--root", str(tmp_path / "nope")).returncode == 2


def test_vendor_and_build_dirs_are_pruned(tmp_path):
    """A vendored SDK's bookkeeping is its author's problem, and it buries real findings."""
    src = _unity(tmp_path)
    (src / "Library").mkdir()
    (src / "Library" / "Cached.cs").write_text("public class Cached { }", encoding="utf-8")
    assert integrity.run(src)["no-meta"] == []
