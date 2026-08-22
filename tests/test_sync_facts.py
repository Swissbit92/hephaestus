"""The drift detector's facts parser, and its refusal to guess.

`sync.py` parses a deliberately narrow YAML subset rather than taking a PyYAML dependency
into a plugin that promises pure stdlib. That trade is fine. What was not fine is that
every input outside the subset produced an empty fact list, which `sync` reported as "no
facts defined" and exited 0 on — and since a drift detector's healthy output is silence,
a completely blind detector was indistinguishable from one with nothing to report.

Three legal YAML inputs did exactly that, measured before the fix: keys in a different
order, flow style, and a trailing comment swallowed into the pattern (producing a regex
that is still valid and can never match). Each has a test below.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import sync

SCRIPT = (Path(__file__).resolve().parent.parent / "plugins" / "crucible" / "skills"
          / "cms" / "scripts" / "sync.py")

GOOD = """facts:
  - name: portfolio-version
    pattern: 'portfolio v(\\d+\\.\\d+\\.\\d+)'
    expected_value: "1.13.1"
"""


def _facts_file(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "sync_facts.yaml"
    p.write_text(body, encoding="utf-8")
    return p


# --------------------------------------------------------------------------- still works
def test_the_documented_layout_still_parses(tmp_path):
    facts = sync.load_facts(_facts_file(tmp_path, GOOD))
    assert len(facts) == 1
    assert facts[0]["name"] == "portfolio-version"
    assert facts[0]["expected_value"] == "1.13.1"


def test_an_empty_starter_is_not_an_error(tmp_path):
    """The shipped state/sync_facts.yaml is comments plus a bare `facts:` key. That is an
    honest empty list, not a parse failure, and must keep loading as one."""
    body = "# CMS drift-detection facts.\n#\n# Add facts as you discover drift.\n\nfacts:\n"
    assert sync.load_facts(_facts_file(tmp_path, body)) == []


# --------------------------------------------------------------------------- the silent three
def test_reordered_keys_are_refused_not_silently_dropped(tmp_path):
    """Legal YAML, semantically identical to GOOD, previously parsed to zero facts."""
    body = """facts:
  - pattern: 'portfolio v(\\d+)'
    name: portfolio-version
    expected_value: "1.13.1"
"""
    with pytest.raises(sync.FactsUnreadable) as e:
        sync.load_facts(_facts_file(tmp_path, body))
    assert "none of it parsed" in str(e.value)


def test_flow_style_is_refused_not_silently_dropped(tmp_path):
    body = 'facts:\n  - {name: v, pattern: \'x(\\d+)\', expected_value: "1.0"}\n'
    with pytest.raises(sync.FactsUnreadable):
        sync.load_facts(_facts_file(tmp_path, body))


def test_a_swallowed_trailing_comment_is_refused(tmp_path):
    """The nastiest of the three: it parses, loads, and reports as an active fact whose
    regex can never match, so the fact is silently inert rather than absent."""
    body = """facts:
  - name: v
    pattern: 'x(\\d+)'   # one capture group
    expected_value: "1.0"
"""
    with pytest.raises(sync.FactsUnreadable) as e:
        sync.load_facts(_facts_file(tmp_path, body))
    assert "can never match" in str(e.value)


# --------------------------------------------------------------------------- typos
def test_an_unknown_key_is_refused(tmp_path):
    body = """facts:
  - name: v
    patern: 'x(\\d+)'
    expected_value: "1.0"
"""
    with pytest.raises(sync.FactsUnreadable) as e:
        sync.load_facts(_facts_file(tmp_path, body))
    assert "patern" in str(e.value)


def test_a_fact_with_no_pattern_is_refused(tmp_path):
    body = 'facts:\n  - name: v\n    expected_value: "1.0"\n'
    with pytest.raises(sync.FactsUnreadable) as e:
        sync.load_facts(_facts_file(tmp_path, body))
    assert "no `pattern`" in str(e.value)


# --------------------------------------------------------------------------- exit codes
def _run(root: Path, facts: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), str(root), "--facts", str(facts)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)


def test_unreadable_facts_exit_2_not_0(tmp_path):
    """2 is 'could not determine'. Reporting it as 0 is how a blind detector passes for a
    clean one; reporting it as 1 would call a config error a drift finding."""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    facts = _facts_file(tmp_path, 'facts:\n  - {name: v, pattern: \'x(\\d+)\'}\n')

    r = _run(root, facts)

    assert r.returncode == 2, r.stdout + r.stderr
    assert "cannot determine" in r.stderr


def test_empty_facts_exit_0_and_the_count_is_always_printed(tmp_path):
    """A count that only appears when non-zero cannot be used to notice that it is zero."""
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    facts = _facts_file(tmp_path, "facts:\n")

    r = _run(root, facts)

    assert r.returncode == 0
    assert "Facts loaded: 0" in r.stdout


def test_a_valid_run_prints_the_count(tmp_path):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "a.md").write_text("portfolio v1.13.1\n", encoding="utf-8")
    facts = _facts_file(tmp_path, GOOD)

    r = _run(root, facts)

    assert "Facts loaded: 1" in r.stdout
    assert r.returncode == 0, r.stdout + r.stderr
