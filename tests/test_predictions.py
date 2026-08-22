"""Tests for the prediction ledger.

The ledger exists so a repo accumulates evidence about whether its justifications were
right, not just a list of changes that each looked sound at the time. Its whole value is
in the `wrong` verdicts, so the tests below are mostly about the ways a record like this
quietly turns into self-congratulation:

- a claim with no check can never be falsified, so it must be refused at the door;
- a check that was never observed failing cannot distinguish success from failure, so a
  prediction must state its baseline — the ledger settled three entries on invalid
  instruments before this was enforced;
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
            check: str = "run the benchmark",
            baseline: str = "the benchmark currently reports 4.2s") -> subprocess.CompletedProcess:
    return _run(repo, "record", ident, "--claim", claim, "--check", check,
                "--baseline", baseline, "--date", "2026-08-16")


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


# --------------------------------------------------------------------------- baseline validity
#
# The claim-side rules (a check is required, a recorded claim is immutable) guard against a
# prediction being *rewritten*. They say nothing about whether its check could ever have
# failed — and that is a separate defect with the same result: a settled entry that looks
# rigorous and measured nothing. Three entries in this repo's own ledger were settled on
# instruments that could not have distinguished success from failure.


def test_record_refuses_a_prediction_with_no_baseline(tmp_path):
    r = _run(tmp_path, "record", "p1", "--claim", "x will get faster",
             "--check", "run the benchmark", "--date", "2026-08-16")
    assert r.returncode == 1
    assert "baseline" in r.stderr.lower()
    assert not (tmp_path / "docs" / "predictions.jsonl").exists()


def test_record_refuses_an_empty_baseline(tmp_path):
    r = _record(tmp_path, baseline="   ")
    assert r.returncode == 1
    assert "baseline" in r.stderr.lower()


def test_a_missing_flag_is_refused_not_reported_as_undetermined(tmp_path):
    """Exit 1 (refused) and exit 2 (could not determine) mean different things here, and
    argparse's own `required=True` squats on 2.

    Written as `required=True`, the carefully-worded refusal text was unreachable except by
    passing an empty string — so a missing --check exited 2, which this script documents as
    "the store is unreadable or malformed", and a caller scripting it could not tell a
    forgotten flag from a corrupt ledger. The repo invariant that a check which could not
    run is never reported as a pass depends on those codes staying distinct.
    """
    for missing in ("--check", "--baseline"):
        args = ["record", "p1", "--claim", "c", "--date", "2026-08-16"]
        for flag, value in (("--check", "k"), ("--baseline", "b")):
            if flag != missing:
                args += [flag, value]
        r = _run(tmp_path, *args)
        assert r.returncode == 1, f"{missing} omitted gave exit {r.returncode}, not 1"
        assert "refused:" in r.stderr, f"{missing} omitted did not reach the refusal message"


def test_the_baseline_is_stored_and_shown(tmp_path):
    _record(tmp_path, baseline="grep finds zero matches today")
    store = tmp_path / "docs" / "predictions.jsonl"
    rec = json.loads(store.read_text(encoding="utf-8").splitlines()[0])
    assert rec["baseline"] == "grep finds zero matches today"

    listing = _run(tmp_path, "list")
    assert listing.returncode == 0
    assert "grep finds zero matches today" in listing.stdout


def test_a_prediction_without_a_baseline_is_flagged_in_the_listing(tmp_path):
    """Entries predating the rule stay readable, but must not pass as equivalent."""
    store = tmp_path / "docs" / "predictions.jsonl"
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({
        "kind": "prediction", "id": "legacy", "date": "2026-01-01",
        "claim": "an old claim", "check": "an old check",
    }) + "\n", encoding="utf-8")

    listing = _run(tmp_path, "list")

    assert listing.returncode == 0
    assert "NOT RECORDED" in listing.stdout
    assert "carry no baseline" in listing.stdout
