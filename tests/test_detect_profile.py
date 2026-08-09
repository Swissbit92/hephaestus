"""Tests for the Phase-4.0 project-profile detector.

The detector's job is to make "which checks does this project actually support" a fact
rather than a guess. These tests pin the cases that make that non-trivial — every one is
drawn from a real repository shape, not invented:

- a project root can be nested (a frontend or a sibling service inside a backend repo),
  so stopping at the first match silently leaves whole subtrees ungated;
- pytest configuration lives in four different files depending on the project;
- some scaffolds put typescript/eslint/jest in `dependencies`, so reading devDependencies
  alone reports a fully-tooled app as having nothing to run;
- "found nothing" and "everything is fine" must never share an exit code.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugins" / "crucible" / "scripts" / "detect_profile.py"


def _load():
    spec = importlib.util.spec_from_file_location("detect_profile", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dp = _load()


def _w(root: Path, rel: str, content: str = "") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _kinds(profiles, root):
    return next((p for p in profiles if p["root"] == root), None)


def _gate_names(profile):
    return {g["name"] for g in profile["gates"]}


# --------------------------------------------------------------------------- python shapes
def test_pytest_config_found_in_pyproject(tmp_path):
    _w(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\ntestpaths = ['tests']\n")
    found, where = dp._pytest_config(tmp_path)
    assert found and "pyproject" in where


def test_pytest_config_found_in_pytest_ini(tmp_path):
    _w(tmp_path, "pytest.ini", "[pytest]\ntestpaths = tests\n")
    found, where = dp._pytest_config(tmp_path)
    assert found and where == "pytest.ini"


def test_pytest_config_found_in_setup_cfg_and_tox(tmp_path):
    _w(tmp_path, "setup.cfg", "[tool:pytest]\ntestpaths = tests\n")
    assert dp._pytest_config(tmp_path)[0] is True
    other = tmp_path / "b"
    _w(other, "tox.ini", "[pytest]\ntestpaths = tests\n")
    assert dp._pytest_config(other)[0] is True


def test_pyproject_without_a_pytest_section_is_not_pytest_config(tmp_path):
    """File existence answers the wrong question — a pyproject may configure only ruff."""
    _w(tmp_path, "pyproject.toml", "[tool.ruff]\nline-length = 100\n")
    assert dp._pytest_config(tmp_path)[0] is False


def test_python_project_with_only_tests_and_requirements_is_still_gateable(tmp_path):
    """Several real repos carry no pyproject.toml at all; requiring one misses them."""
    _w(tmp_path, "requirements.txt", "requests\n")
    _w(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
    prof = dp._python_profile(tmp_path, "")
    assert prof is not None
    assert "tests" in _gate_names(prof)
    assert any("no pytest config" in n for n in prof["notes"])


def test_python_lint_and_typecheck_gates_come_from_config(tmp_path):
    _w(tmp_path, "pyproject.toml",
       "[tool.pytest.ini_options]\ntestpaths=['tests']\n[tool.ruff]\nline-length=120\n"
       "[tool.mypy]\npython_version='3.12'\n")
    names = _gate_names(dp._python_profile(tmp_path, ""))
    assert {"tests", "lint", "format", "typecheck", "coverage-delta"} <= names


def test_coverage_threshold_is_reported_not_imposed(tmp_path):
    _w(tmp_path, "pyproject.toml",
       "[tool.pytest.ini_options]\naddopts = '--cov=x --cov-fail-under=75'\n")
    prof = dp._python_profile(tmp_path, "")
    assert any("75%" in n for n in prof["notes"])
    assert all("75" not in g["cmd"] for g in prof["gates"]), "threshold must not be baked into a command"


# --------------------------------------------------------------------------- node shapes
def test_tooling_in_dependencies_is_found_not_just_devdependencies(tmp_path):
    """Some scaffolds put typescript/eslint/jest in `dependencies`. Reading devDependencies
    alone would report this fully-tooled app as having no gates."""
    _w(tmp_path, "package.json", json.dumps({
        "name": "app",
        "dependencies": {"react": "19", "typescript": "4.9.5", "eslint": "^8", "jest": "^29"},
        "devDependencies": {},
        "scripts": {"build": "react-scripts build", "test": "react-scripts test"},
    }))
    _w(tmp_path, "tsconfig.json", "{}")
    names = _gate_names(dp._node_profile(tmp_path, ""))
    assert {"build", "lint", "tests"} <= names


def test_declared_scripts_win_over_guessed_commands(tmp_path):
    _w(tmp_path, "package.json", json.dumps({
        "scripts": {"lint": "biome check", "test": "vitest run"},
        "devDependencies": {"eslint": "^8"},
    }))
    gates = {g["name"]: g["cmd"] for g in dp._node_profile(tmp_path, "")["gates"]}
    assert gates["lint"] == "npm run lint"
    assert gates["test" if "test" in gates else "tests"] == "npm test"


def test_playwright_without_webserver_is_a_capability_not_a_gate(tmp_path):
    """An e2e run against a server that is not up collects zero tests, and zero tests
    passing is the classic vacuous green."""
    _w(tmp_path, "package.json", json.dumps({
        "scripts": {"build": "vite build"},
        "devDependencies": {"@playwright/test": "^1.58"},
    }))
    _w(tmp_path, "playwright.config.ts", "export default { use: { baseURL: 'http://localhost:3001' } }")
    e2e = next(g for g in dp._node_profile(tmp_path, "")["gates"] if g["name"] == "e2e")
    assert e2e["kind"] == dp.CAPABILITY
    assert e2e["kind"] != dp.GATE


def test_playwright_with_webserver_is_a_real_gate(tmp_path):
    _w(tmp_path, "package.json", json.dumps({
        "scripts": {"build": "vite build"},
        "devDependencies": {"@playwright/test": "^1.58"},
    }))
    _w(tmp_path, "playwright.config.ts",
       "export default { webServer: { command: 'npm start', port: 3001 } }")
    e2e = next(g for g in dp._node_profile(tmp_path, "")["gates"] if g["name"] == "e2e")
    assert e2e["kind"] == dp.GATE


def test_playwright_installed_but_unconfigured_is_never_gated(tmp_path):
    _w(tmp_path, "package.json", json.dumps({
        "scripts": {"build": "vite build"},
        "devDependencies": {"@playwright/test": "^1.58"},
    }))
    prof = dp._node_profile(tmp_path, "")
    assert "e2e" not in _gate_names(prof)
    assert any("installed is not wired" in n for n in prof["notes"])


# --------------------------------------------------------------------------- walking
def test_finds_nested_roots_and_does_not_stop_at_the_first(tmp_path):
    """The case a root-only detector fails: a backend repo containing a frontend and a
    second, independent service. Stopping at the root leaves both ungated."""
    _w(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\ntestpaths=['tests']\n")
    _w(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
    _w(tmp_path, "web/package.json", json.dumps({"scripts": {"build": "vite build", "test": "vitest"}}))
    _w(tmp_path, "services/gw/pyproject.toml",
       "[tool.pytest.ini_options]\ntestpaths=['tests']\n[tool.ruff]\nline-length=120\n")

    profiles = dp.detect(tmp_path)
    roots = {p["root"] for p in profiles}
    assert roots == {".", "web", "services/gw"}, f"expected all three roots, got {roots}"
    assert _kinds(profiles, "web")["kind"] == "node"
    assert "lint" in _gate_names(_kinds(profiles, "services/gw"))


def test_walk_prunes_dependency_and_venv_dirs(tmp_path):
    _w(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\ntestpaths=['tests']\n")
    _w(tmp_path, "node_modules/pkg/package.json", json.dumps({"scripts": {"build": "x"}}))
    _w(tmp_path, ".venv/lib/pyproject.toml", "[tool.pytest.ini_options]\n")
    roots = {p["root"] for p in dp.detect(tmp_path)}
    assert roots == {"."}, f"vendored trees must not be reported as project roots: {roots}"


def test_max_depth_bounds_the_walk(tmp_path):
    _w(tmp_path, "a/b/c/d/package.json", json.dumps({"scripts": {"build": "x"}}))
    assert dp.detect(tmp_path, max_depth=2) == []
    assert {p["root"] for p in dp.detect(tmp_path, max_depth=4)} == {"a/b/c/d"}


# --------------------------------------------------------------------------- exit codes
def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=120)


def test_exit_3_when_no_markers_and_it_says_so(tmp_path):
    """Skip must be distinguishable from a clean pass, in the exit code and in the words."""
    p = _run("--repo", str(tmp_path))
    assert p.returncode == 3
    combined = p.stdout + p.stderr
    assert "SKIP, not a pass" in combined


def test_exit_2_on_malformed_manifest(tmp_path):
    _w(tmp_path, "package.json", "{not json")
    p = _run("--repo", str(tmp_path))
    assert p.returncode == 2
    assert "cannot determine" in (p.stdout + p.stderr)


def test_exit_2_on_missing_path():
    p = _run("--repo", "/nonexistent/path/xyz")
    assert p.returncode == 2


def test_exit_0_and_json_shape(tmp_path):
    _w(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\ntestpaths=['tests']\n")
    _w(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
    p = _run("--repo", str(tmp_path), "--json")
    assert p.returncode == 0, p.stderr
    data = json.loads(p.stdout)
    assert data[0]["root"] == "." and data[0]["kind"] == "python"
    assert all({"name", "cmd", "kind"} <= set(g) for g in data[0]["gates"])


def test_emit_gates_excludes_capabilities(tmp_path):
    """The split has to be load-bearing, not decorative. A capability emitted as a runnable
    command would eventually be run against a service that is not up, collect nothing, and
    exit clean — a vacuous pass wearing the costume of a gate."""
    _w(tmp_path, "package.json", json.dumps({
        "scripts": {"build": "vite build", "test": "vitest run"},
        "devDependencies": {"@playwright/test": "^1.58"}}))
    _w(tmp_path, "playwright.config.ts", "export default { use: { baseURL: 'http://x' } }")
    runnable, notes = dp.emit_gates(dp.detect(tmp_path))
    assert "npm run build" in runnable and "npm test" in runnable
    assert "playwright" not in runnable, "a capability must never be emitted as runnable"
    assert "playwright" in notes and "capability (not gated)" in notes


def test_emit_gates_prefixes_nested_roots_with_a_cd(tmp_path):
    _w(tmp_path, "pyproject.toml", "[tool.pytest.ini_options]\ntestpaths=['tests']\n")
    _w(tmp_path, "tests/test_a.py", "def test_a():\n    assert True\n")
    _w(tmp_path, "web/package.json", json.dumps({"scripts": {"test": "vitest"}}))
    runnable, _ = dp.emit_gates(dp.detect(tmp_path))
    lines = runnable.splitlines()
    assert any(l == "python3 -m pytest" for l in lines), "root gate needs no cd"
    assert any(l.startswith("cd web && ") for l in lines), "nested gate must cd first"


def test_emit_gates_exits_3_when_only_capabilities_exist(tmp_path):
    """Capability-only is a SKIP, never a pass — nothing was checked."""
    _w(tmp_path, "package.json", json.dumps({"devDependencies": {"@playwright/test": "^1"}}))
    _w(tmp_path, "playwright.config.ts", "export default { webServer: { command: 'x' } }")
    p = _run("--repo", str(tmp_path), "--emit-gates")
    assert p.returncode in (0, 3)
    if p.returncode == 3:
        assert "SKIP, not a pass" in (p.stdout + p.stderr)


def test_detector_never_executes_anything(tmp_path):
    """It reports commands; running them is the caller's trust decision. A marker file
    whose script would have a side effect must leave no trace."""
    sentinel = tmp_path / "SIDE_EFFECT"
    _w(tmp_path, "package.json", json.dumps({
        "scripts": {"build": f"touch {sentinel}", "test": f"touch {sentinel}"}}))
    p = _run("--repo", str(tmp_path))
    assert p.returncode == 0
    assert not sentinel.exists(), "detector must never run a discovered script"
