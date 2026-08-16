"""Tests for the prediction ledger.

The ledger exists so a repo accumulates evidence about whether its justifications were
right, not just a list of changes that each looked sound at the time. Its whole value is
in the `wrong` verdicts, so the tests below are mostly about the ways a record like this
quietly turns into self-congratulation:

- a claim with no check can never be falsified, so it must be refused at the door;
- a recorded claim must be immutable, because editing it to match the outcome is both the
  natural move and the one that destroys the record;
- "unclear" must be a first-class verdict, since forcing a binary answer onto an ambiguous
  outcome is how the file becomes fiction;
- an unreadable store is "could not determine", never an empty ledger reported as clean.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import predictions as pr

SCRIPT = (Path(__file__).resolve().parent.parent / "plugins" / "crucible" / "scripts"
          / "predictions.py")


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)


def _record(repo: Path, ident: str = "p1", claim: str = "x will get faster",
            check: str = "run the benchmark") -> subprocess.CompletedProcess:
    return _run(repo, "record", ident, "--claim", claim, "--check", check,
                "--date", "2026-08-16")


# --------------------------------------------------------------------------- falsifiability
def test_a_prediction_without_a_check_is_refused(tmp_path):
    """A claim with no way to settle it is always graded correct in hindsight."""
    r = _run(tmp_path, "record", "p1", "--claim", "it will be better",
             "--check", "   ", "--date", "2026-08-16")
    assert r.returncode == 1
    assert "cannot be wrong" in r.stderr


def test_a_recorded_prediction_cannot_be_rewritten(tmp_path):
    """Editing the claim to match the result is the natural move when the result is
    embarrassing, and it is exactly what this ledger exists to prevent."""
    assert _record(tmp_path).returncode == 0
    r = _record(tmp_path, claim="something I now believe instead")
    assert r.returncode == 1
    assert "immutable" in r.stderr


# --------------------------------------------------------------------------- the ledger
def test_the_store_is_append_only_and_keeps_the_original_words(tmp_path):
    _record(tmp_path, claim="the hook will block bad frontmatter")
    _run(tmp_path, "verify", "p1", "--verdict", "wrong",
         "--evidence", "it blocked nothing in 20 edits", "--date", "2026-08-20")
    lines = (tmp_path / "docs" / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, "verification appends; it must never rewrite"
    pred, outcome = json.loads(lines[0]), json.loads(lines[1])
    assert pred["claim"] == "the hook will block bad frontmatter"
    assert outcome["verdict"] == "wrong" and outcome["id"] == pred["id"]


def test_verifying_an_unknown_id_fails_rather_than_inventing_a_record(tmp_path):
    r = _run(tmp_path, "verify", "nope", "--verdict", "right", "--date", "2026-08-20")
    assert r.returncode == 1
    assert "not recorded" in r.stderr


def test_a_prediction_cannot_be_verified_twice(tmp_path):
    _record(tmp_path)
    _run(tmp_path, "verify", "p1", "--verdict", "right", "--date", "2026-08-20")
    r = _run(tmp_path, "verify", "p1", "--verdict", "wrong", "--date", "2026-08-21")
    assert r.returncode == 1
    assert "already verified" in r.stderr


def test_unclear_is_an_accepted_verdict(tmp_path):
    """Forcing a binary answer onto an ambiguous outcome is how the record becomes
    fiction, and an honest 'could not tell' is itself a finding about the claim."""
    _record(tmp_path)
    assert _run(tmp_path, "verify", "p1", "--verdict", "unclear",
                "--date", "2026-08-20").returncode == 0


def test_open_predictions_exclude_verified_ones(tmp_path):
    _record(tmp_path, "a")
    _record(tmp_path, "b")
    _run(tmp_path, "verify", "a", "--verdict", "right", "--date", "2026-08-20")
    records = pr.load(tmp_path / "docs" / "predictions.jsonl")
    assert set(pr.open_predictions(records)) == {"b"}


# --------------------------------------------------------------------------- reporting
def test_list_says_so_when_nothing_has_ever_been_wrong(tmp_path):
    """A ledger with no misses is far more likely to be measuring nothing than to be
    describing perfection, and it should say so rather than read as a clean bill."""
    _record(tmp_path)
    _run(tmp_path, "verify", "p1", "--verdict", "right", "--date", "2026-08-20")
    out = _run(tmp_path, "list").stdout
    assert "too safe to be informative" in out or "too generous" in out


def test_list_is_quiet_about_that_once_something_was_wrong(tmp_path):
    _record(tmp_path, "a")
    _run(tmp_path, "verify", "a", "--verdict", "wrong", "--date", "2026-08-20")
    assert "too generous" not in _run(tmp_path, "list").stdout


def test_list_on_an_empty_repo_is_not_an_error(tmp_path):
    r = _run(tmp_path, "list")
    assert r.returncode == 0 and "no predictions" in r.stdout


# --------------------------------------------------------------------------- exit codes
def test_a_malformed_store_is_could_not_determine_not_an_empty_ledger(tmp_path):
    store = tmp_path / "docs" / "predictions.jsonl"
    store.parent.mkdir(parents=True)
    store.write_text('{"kind": "prediction"\nnot json\n', encoding="utf-8")
    r = _run(tmp_path, "list")
    assert r.returncode == 2, "an unreadable ledger must not report as a clean one"
    assert "cannot determine" in r.stderr


def test_a_missing_repo_is_could_not_determine():
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", "nope/nowhere", "list"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60)
    assert r.returncode == 2
