"""The suite's own temp-dir hygiene.

`conftest.py` redirects cms and loop-harness state into throwaway temp dirs at *import*
time, because both modules mkdir their STATE_DIR when they are imported. The obvious
spelling of that — `os.environ.setdefault(var, tempfile.mkdtemp(...))` — leaked one
directory per variable per pytest process, since the argument is evaluated before
setdefault can decline it. ~490 empty dirs had accumulated in %TEMP% before this was
caught. These tests pin both halves of the fix: the guard, and the teardown.
"""
from __future__ import annotations

import os
from pathlib import Path

import conftest


def test_already_set_var_creates_no_directory(tmp_path, monkeypatch):
    """The regression itself: a var that is already set must cost zero mkdtemp calls."""
    monkeypatch.setenv("HEPHAESTUS_TEST_STATE_VAR", str(tmp_path))
    monkeypatch.setattr(conftest, "_OWNED_TEMP_DIRS", [])

    conftest._isolate_state_dir("HEPHAESTUS_TEST_STATE_VAR", "hephaestus-should-not-exist-")

    assert os.environ["HEPHAESTUS_TEST_STATE_VAR"] == str(tmp_path)
    assert conftest._OWNED_TEMP_DIRS == []
    leaked = list(Path(tmp_path.parent).glob("hephaestus-should-not-exist-*"))
    assert leaked == [], f"mkdtemp ran despite the var being set: {leaked}"


def test_unset_var_gets_a_directory_that_is_recorded_as_ours(monkeypatch):
    monkeypatch.delenv("HEPHAESTUS_TEST_STATE_VAR", raising=False)
    owned: list[str] = []
    monkeypatch.setattr(conftest, "_OWNED_TEMP_DIRS", owned)

    conftest._isolate_state_dir("HEPHAESTUS_TEST_STATE_VAR", "hephaestus-owned-test-")

    created = os.environ["HEPHAESTUS_TEST_STATE_VAR"]
    try:
        assert Path(created).is_dir()
        assert owned == [created], "a dir we created must be recorded for teardown"
    finally:
        conftest.pytest_unconfigure(None)


def test_unconfigure_removes_only_recorded_dirs(tmp_path, monkeypatch):
    """Teardown must never reach a directory the caller supplied."""
    caller_owned = tmp_path / "not-ours"
    caller_owned.mkdir()
    monkeypatch.delenv("HEPHAESTUS_TEST_STATE_VAR", raising=False)
    owned: list[str] = []
    monkeypatch.setattr(conftest, "_OWNED_TEMP_DIRS", owned)
    conftest._isolate_state_dir("HEPHAESTUS_TEST_STATE_VAR", "hephaestus-owned-test-")
    ours = Path(os.environ["HEPHAESTUS_TEST_STATE_VAR"])

    conftest.pytest_unconfigure(None)

    assert not ours.exists(), "our own temp dir survived teardown"
    assert caller_owned.is_dir(), "teardown deleted a directory it did not create"
    assert owned == []


def test_unconfigure_survives_an_undeletable_directory(monkeypatch):
    """A cleanup failure must not turn a green Windows run red — hence ignore_errors."""
    monkeypatch.setattr(conftest, "_OWNED_TEMP_DIRS", ["/nonexistent/path/that/is/not/there"])
    conftest.pytest_unconfigure(None)  # must not raise
    assert conftest._OWNED_TEMP_DIRS == []
