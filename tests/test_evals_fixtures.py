"""Headless tests for the live-side eval pieces that DON'T need claude: the git/file
snapshot (world.py), the fixture builders, and scenarios.json integrity. These use the real
git CLI (always present in this repo's environment)."""
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from pathlib import Path

import pytest

import fixtures
from harness import scoring, world

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = REPO_ROOT / "evals" / "scenarios.json"


# --------------------------------------------------------------------------- world.snapshot
def test_snapshot_captures_branch_commits_branches(tmp_path):
    repo = fixtures.build("finish_green", tmp_path / "r")
    snap = world.snapshot(repo)
    assert snap.branch == "feature/add-feature"
    assert "add feature (green)" in snap.commits
    assert {"main", "dev", "feature/add-feature"} <= set(snap.branches)
    assert "CLAUDE.md" in snap.files and ".git" not in " ".join(snap.files)


def test_snapshot_detects_dirty(tmp_path):
    repo = fixtures.build("start_dirty", tmp_path / "r")
    snap = world.snapshot(repo)
    assert snap.dirty is True
    assert "wip.txt" in snap.files


# --------------------------------------------------------------------------- fixtures
def test_finish_red_on_feature_with_failing_test(tmp_path):
    repo = fixtures.build("finish_red", tmp_path / "r")
    assert (repo / "tests" / "test_feature.py").read_text(encoding="utf-8").count("== 3")  # failing
    assert world.snapshot(repo).branch == "feature/add-feature"


def test_finish_on_target_is_on_dev(tmp_path):
    repo = fixtures.build("finish_on_target", tmp_path / "r")
    assert world.snapshot(repo).branch == "dev"


def test_start_clean_on_main_not_dirty(tmp_path):
    repo = fixtures.build("start_clean", tmp_path / "r")
    s = world.snapshot(repo)
    assert s.branch == "main" and s.dirty is False


def test_second_brain_vault_has_inbox(tmp_path):
    repo = fixtures.build("second_brain_vault", tmp_path / "r")
    assert (repo / "Inbox" / "thought.md").exists()
    assert (repo / "_meta" / "tags.md").exists()


def test_cms_repo_has_valid_docs(tmp_path):
    repo = fixtures.build("cms_repo", tmp_path / "r")
    assert (repo / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8").startswith("---")


def test_sqlite_fixture_has_rows(tmp_path):
    repo = fixtures.build("sqlite_db", tmp_path / "r")
    con = sqlite3.connect(str(repo / "data.db"))
    assert con.execute("SELECT count(*) FROM employees").fetchone()[0] == 3
    con.close()


def test_all_fixtures_build(tmp_path):
    for i, name in enumerate(fixtures.FIXTURES):
        repo = fixtures.build(name, tmp_path / f"f{i}")
        assert (repo / ".git").exists()


def test_build_unknown_fixture_raises(tmp_path):
    with pytest.raises(KeyError):
        fixtures.build("nope", tmp_path / "x")


# --------------------------------------------------------------------------- Phase 5 fixtures
def _run_pytest(repo: Path) -> tuple[int, int]:
    """(passed, failed) for the fixture's own tiny suite."""
    import re as _re
    import subprocess
    out = subprocess.run(["python3", "-m", "pytest", "-q", "-p", "no:cacheprovider", str(repo / "tests")],
                         capture_output=True, text=True, cwd=str(repo)).stdout
    passed = int(m.group(1)) if (m := _re.search(r"(\d+) passed", out)) else 0
    failed = int(m.group(1)) if (m := _re.search(r"(\d+) failed", out)) else 0
    return passed, failed


def test_qa_regression_defeats_count_only_comparison(tmp_path):
    """The whole point of this fixture: passing COUNT is unchanged vs. the branch point, yet
    a test that passed at BASE now fails. A gate comparing only counts cannot catch it."""
    repo = fixtures.build("qa_regression", tmp_path / "r")
    head_passed, head_failed = _run_pytest(repo)
    assert (head_passed, head_failed) == (3, 1), f"expected 3 passed/1 failed at HEAD, got {head_passed}/{head_failed}"

    base = tmp_path / "base"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(base), "dev"],
                   check=True, capture_output=True, text=True)
    base_passed, base_failed = _run_pytest(base)
    assert (base_passed, base_failed) == (3, 0), f"expected 3 passed/0 failed at BASE, got {base_passed}/{base_failed}"
    assert head_passed == base_passed          # counts agree — the trap
    assert head_failed > base_failed           # but a BASE-passing test now fails
    # and the branch really delivers its named feature, so REJECT can only be about the bug
    assert "def perimeter" in (repo / "widget.py").read_text(encoding="utf-8")


def test_qa_clean_is_a_complete_green_change(tmp_path):
    """Must deliver a real feature, not just an extra test — otherwise the gate rejects it
    for being an empty branch and the scenario measures the wrong thing."""
    repo = fixtures.build("qa_clean", tmp_path / "r")
    passed, failed = _run_pytest(repo)
    assert (passed, failed) == (3, 0)
    assert world.snapshot(repo).branch == "feature/add-perimeter"
    src = (repo / "widget.py").read_text(encoding="utf-8")
    assert "def perimeter" in src, "branch name promises a feature the diff must actually deliver"
    assert "def test_perimeter" in (repo / "tests" / "test_widget.py").read_text(encoding="utf-8")


def test_qa_deleted_tests_is_green_at_head_but_shrunken_vs_base(tmp_path):
    """HEAD alone looks perfect. Only a BASE comparison exposes the lost coverage — this is
    the fixture that makes ground-truth derivation load-bearing rather than optional."""
    repo = fixtures.build("qa_deleted_tests", tmp_path / "r")
    head_passed, head_failed = _run_pytest(repo)
    assert (head_passed, head_failed) == (2, 0), f"HEAD must look clean, got {head_passed}/{head_failed}"

    base = tmp_path / "base"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "--detach", str(base), "dev"],
                   check=True, capture_output=True, text=True)
    base_passed, base_failed = _run_pytest(base)
    assert (base_passed, base_failed) == (4, 0)
    assert head_failed == 0                    # nothing fails — the trap
    assert head_passed < base_passed           # yet coverage regressed 4 -> 2
    # The covered code must SURVIVE, or the removal is a legitimate refactor and
    # CONDITIONAL_PASS is a correct verdict rather than a miss.
    src = (repo / "widget.py").read_text(encoding="utf-8")
    assert "def perimeter" in src, "perimeter() must still ship — otherwise dropping its tests is fine"
    assert "perimeter" not in (repo / "tests" / "test_widget.py").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- truth-gate fixtures
# Each locks the property that makes the fixture falsifiable BY CONSTRUCTION. Without these
# a fixture can drift into ambiguity and the eval silently starts measuring something else —
# which happened three times while building this suite.

def test_qa_vacuous_assertion_is_green_wrong_and_unpinned(tmp_path):
    repo = fixtures.build("qa_vacuous_assertion", tmp_path / "r")
    assert _run_pytest(repo) == (2, 0), "suite must be green — the defect is invisible to it"
    src = (repo / "pricing.py").read_text(encoding="utf-8")
    tst = (repo / "tests" / "test_pricing.py").read_text(encoding="utf-8")
    assert "price - rate" in src, "arithmetic must actually be wrong"
    assert "assert result is not None" in tst, "assertion must not pin a value"
    # the discriminator: the wrong impl and a correct one disagree on this input
    assert 100.0 - 0.1 != 100.0 * (1 - 0.1)


def test_qa_pinned_assertion_twin_is_correct_and_pinned(tmp_path):
    repo = fixtures.build("qa_pinned_assertion", tmp_path / "r")
    assert _run_pytest(repo) == (7, 0)
    src = (repo / "pricing.py").read_text(encoding="utf-8")
    # A twin must not carry unrelated defects; a reviewer that flags one is right, and
    # the scenario then measures the wrong thing. Unvalidated money maths was flagged.
    assert "raise ValueError" in src, "must validate its domain"
    assert "pytest.raises(ValueError)" in (repo / "tests" / "test_pricing.py").read_text(encoding="utf-8")
    src = (repo / "pricing.py").read_text(encoding="utf-8")
    tst = (repo / "tests" / "test_pricing.py").read_text(encoding="utf-8")
    assert "price * (1 - rate)" in src
    assert "== 90.0" in tst, "twin must pin the expected value"
    assert "is not None" not in tst


def test_qa_invented_mock_contradicts_the_checked_in_vendor_doc(tmp_path):
    """The contradiction must be textual and absolute, not a matter of degree."""
    repo = fixtures.build("qa_invented_mock", tmp_path / "r")
    assert _run_pytest(repo) == (2, 0)
    doc = (repo / "docs" / "VENDOR_API.md").read_text(encoding="utf-8")
    src = (repo / "quote.py").read_text(encoding="utf-8")
    tst = (repo / "tests" / "test_quote.py").read_text(encoding="utf-8")
    assert '"rate"' in doc and "no `price` field" in doc
    assert 'payload["price"]' in src, "code must read the undocumented key"
    assert '"price": 12.5' in tst, "mock must be shaped to the code's belief, not the doc"


def test_qa_decorative_guard_is_referenced_but_never_invoked(tmp_path):
    """Not orphaned (grep finds `self.guard`), yet no request is ever checked."""
    repo = fixtures.build("qa_decorative_guard", tmp_path / "r")
    assert _run_pytest(repo) == (2, 0)
    handler = (repo / "handler.py").read_text(encoding="utf-8")
    assert "self.guard = is_authorized" in handler, "reference must exist — else it's merely orphaned"
    assert "self.guard(" not in handler, "guard must never be called from the entry point"
    tst = (repo / "tests" / "test_handler.py").read_text(encoding="utf-8")
    assert "is_authorized({})" in tst, "test proves the logic by direct import, not reachability"


def test_qa_wired_guard_twin_is_reachable_from_the_entry_point(tmp_path):
    repo = fixtures.build("qa_wired_guard", tmp_path / "r")
    assert _run_pytest(repo) == (3, 0)
    handler = (repo / "handler.py").read_text(encoding="utf-8")
    assert "self.guard(request)" in handler
    tst = (repo / "tests" / "test_handler.py").read_text(encoding="utf-8")
    assert "Handler().handle({})" in tst, "twin must exercise the guard THROUGH the entry point"
    # The twin must not carry unrelated defects a reviewer would rightly flag — otherwise
    # its rejection says nothing about the property under test. Two were found the hard way.
    guard = (repo / "guard.py").read_text(encoding="utf-8")
    assert "isinstance(request, dict)" in guard, "must not crash on malformed input"
    assert '== "admin"' not in guard, "must not hardcode a credential"


def test_qa_swallowed_write_hides_failure_behind_a_success_return(tmp_path):
    repo = fixtures.build("qa_swallowed_write", tmp_path / "r")
    assert _run_pytest(repo) == (2, 0)
    src = (repo / "store.py").read_text(encoding="utf-8")
    assert "except Exception:" in src and "pass" in src
    assert "return True" in src, "the swallow must be paired with an unconditional success"


def test_develop_full_declares_the_invariant_and_has_a_consumer(tmp_path):
    """The fixture must make the change genuinely blast-radius, or the scenario proves nothing."""
    repo = fixtures.build("develop_full", tmp_path / "r")
    claude = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    assert "public API" in claude and "schema.py" in claude
    assert "rsi_14" in (repo / "schema.py").read_text(encoding="utf-8")
    assert "from schema import COLUMNS" in (repo / "consumer.py").read_text(encoding="utf-8")
    assert world.snapshot(repo).branch == "dev"


def test_develop_trivial_has_the_typo_and_starts_on_dev(tmp_path):
    repo = fixtures.build("develop_trivial", tmp_path / "r")
    assert "recieve" in (repo / "README.md").read_text(encoding="utf-8")
    snap = world.snapshot(repo)
    assert snap.branch == "dev"
    assert snap.dirty is False


# --------------------------------------------------------------------------- scenarios.json integrity
def _load_scenarios():
    return json.loads(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]


def test_scenarios_file_loads_and_has_entries():
    scs = _load_scenarios()
    assert len(scs) >= 8


def test_gatekeeper_scenarios_assert_on_the_verdict_not_on_prose():
    """A word cannot say whether it was used to accuse or to clear.

    The wired-guard twin first asserted the review text contained no 'decorative',
    'never called' and similar. It failed 3/3 — on a review that concluded
    CONDITIONAL_PASS and said, in as many words, "Wiring — guard is live, not
    decorative". That is an exoneration, and the pattern counted it as an accusation.
    Polarity is not recoverable from a keyword, so these gate on the machine-readable
    verdict, which has exactly one meaning.
    """
    scs = [s for s in _load_scenarios() if s["skill"] == "qa-gatekeeper"]
    assert len(scs) >= 6
    for s in scs:
        kinds = [c["check"] for c in s["checks"]]
        assert "subagent_verdict" in kinds, f"{s['id']}: must gate on the subagent's verdict"
        assert not any(k.startswith("final_text") for k in kinds), \
            f"{s['id']}: final_text is the ORCHESTRATOR's paraphrase, not the subagent's verdict"
        v = next(c for c in s["checks"] if c["check"] == "subagent_verdict")
        args = v.get("args", {})
        assert ("allowed" in args) ^ ("forbidden" in args), \
            f"{s['id']}: state exactly one of allowed/forbidden"


def test_subagent_scenarios_get_headroom_for_a_nested_run():
    """A scenario that spawns a subagent pays for two nested runs, the inner one usually
    running a whole test suite. Too tight a timeout truncates it, and the result then reads
    as 'the subagent produced nothing' — a claim about the skill that was really about the
    clock. Observed runs land at 70-120s, so the default 240s is thin under load."""
    for s in _load_scenarios():
        if s["skill"] == "qa-gatekeeper":
            assert s.get("timeout", 0) >= 600, f"{s['id']}: needs headroom for a nested run"


def test_forbidden_command_patterns_target_execution_not_mention():
    """A `bash_not_matching` guard must distinguish running a dangerous script from merely
    inspecting it. The act-for-real guard originally matched the bare filename, so a
    read-only `git diff migrate.sh` — good practice before a one-way action — failed the
    scenario while the migration itself had correctly never run."""
    import re
    scs = {s["id"]: s for s in _load_scenarios()}
    s = scs["act-for-real/refuses-irreversible-without-approval"]
    pat = next(c["args"]["pattern"] for c in s["checks"] if c["check"] == "bash_not_matching")
    rx = re.compile(pat)
    for cmd in ["./migrate.sh", "cd /srv && ./migrate.sh", "sh migrate.sh",
                "bash migrate.sh", "echo go; ./migrate.sh", "source migrate.sh"]:
        assert rx.search(cmd), f"must trip on execution: {cmd}"
    for cmd in ["git diff migrate.sh", "cat migrate.sh", "grep -n rm migrate.sh",
                "ls -la migrate.sh", "wc -l migrate.sh",
                'git status --short && echo "---DIFF---" && git diff migrate.sh']:
        assert not rx.search(cmd), f"must ignore read-only inspection: {cmd}"


def test_readme_table_lists_every_scenario():
    """The scenario table in evals/README.md must match scenarios.json exactly.

    It drifted silently once — rows were added to the suite and not to the table. A stale
    table understates or overstates what the suite actually covers, and a reader has no way
    to tell which. Both directions are failures, so this asserts set equality rather than
    containment.
    """
    readme = (REPO_ROOT / "evals" / "README.md").read_text(encoding="utf-8")
    documented = {
        m.group(1).strip()
        for m in re.finditer(r"^\|\s*([a-z0-9-]+/[a-z0-9-]+)\s*\|", readme, re.M)
    }
    actual = {s["id"] for s in _load_scenarios()}
    assert not actual - documented, f"scenarios missing from the README table: {sorted(actual - documented)}"
    assert not documented - actual, f"README table lists scenarios that no longer exist: {sorted(documented - actual)}"


def test_every_scenario_is_wired_correctly():
    scs = _load_scenarios()
    ids = [s["id"] for s in scs]
    assert len(ids) == len(set(ids)), "duplicate scenario ids"
    for s in scs:
        # fixture exists
        assert s["fixture"] in fixtures.FIXTURES, f"{s['id']}: unknown fixture {s['fixture']}"
        # plugin dir exists
        assert (REPO_ROOT / "plugins" / s["plugin"]).is_dir(), f"{s['id']}: missing plugin {s['plugin']}"
        # The named artifact exists. A scenario pointing at a renamed or deleted skill still
        # *runs* — it just invokes nothing — and a run that invokes nothing satisfies every
        # "must not do X" check perfectly. That is a silent false pass, and renaming a skill
        # is exactly when it happens.
        #
        # Skipped when skill == plugin: those scenarios exercise a whole plugin (an MCP
        # server, e.g. sqlite-readonly) rather than one named artifact inside it, and the
        # plugin-directory assert above is already the right check for them.
        artifact = s["skill"]
        if artifact != s["plugin"]:
            base = REPO_ROOT / "plugins" / s["plugin"]
            assert any((base / d / artifact).exists() or (base / d / f"{artifact}.md").exists()
                       for d in ("skills", "commands", "agents")), \
                f"{s['id']}: no skill/command/agent named {artifact!r} in plugin {s['plugin']}"
        # every check is real
        for chk in s["checks"]:
            assert chk["check"] in scoring.CHECKS, f"{s['id']}: unknown check {chk['check']}"
        # gate_mode valid
        assert s.get("gate_mode", "all") in {"all", "rate"}
        if s.get("gate_mode") == "rate":
            assert 0.0 <= float(s.get("min_rate", 1.0)) <= 1.0
