"""Tests for the loop-harness skill scripts (budget/ledger/safety-hook).

Pure logic is unit-tested directly; the CLIs and the hook are driven via subprocess with an
isolated LOOP_HARNESS_STATE_DIR so nothing touches the plugin's real state dir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import loop_budget
import loop_common
import loop_hook
import loop_ledger
import loop_logscan
import pytest

BUDGET_PY = Path(loop_budget.__file__)
LEDGER_PY = Path(loop_ledger.__file__)
HOOK_PY = Path(loop_hook.__file__)
LOGSCAN_PY = Path(loop_logscan.__file__)


def _run_cli(script: Path, args, state_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["LOOP_HARNESS_STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, env=env,
    )


# --- pure: new_run / charge / check_budget / remaining ---

def test_new_run_defaults_and_fields():
    run = loop_budget.new_run("fix CI", 10, started_at="2026-06-28T00:00:00+00:00")
    assert run["max_turns"] == 10
    assert run["turns"] == 0 and run["tokens"] == 0 and run["cost_usd"] == 0.0
    assert run["max_tokens"] is None and run["max_cost_usd"] is None
    assert run["goal"] == "fix CI"
    assert run["run_id"] == "loop-2026-06-28T00:00:00+00:00"


def test_new_run_rejects_nonpositive_turns():
    with pytest.raises(ValueError):
        loop_budget.new_run("x", 0)
    with pytest.raises(ValueError):
        loop_budget.new_run("x", -3)


def test_charge_is_pure_and_accumulates():
    run = loop_budget.new_run("x", 5)
    once = loop_budget.charge(run, turns=1, tokens=100, cost_usd=0.01)
    assert run["turns"] == 0  # original untouched
    assert once["turns"] == 1 and once["tokens"] == 100 and once["cost_usd"] == 0.01
    twice = loop_budget.charge(once, turns=1, tokens=50, cost_usd=0.02)
    assert twice["turns"] == 2 and twice["tokens"] == 150 and twice["cost_usd"] == 0.03


def test_check_budget_turn_ceiling_is_hard():
    run = loop_budget.new_run("x", 2)
    ok, _ = loop_budget.check_budget(loop_budget.charge(run))  # 1/2
    assert ok
    over = loop_budget.charge(loop_budget.charge(run))  # 2/2
    ok, reason = loop_budget.check_budget(over)
    assert not ok and "turn ceiling" in reason


def test_check_budget_optional_token_and_cost_ceilings():
    run = loop_budget.new_run("x", 100, max_tokens=1000, max_cost_usd=1.0)
    ok, reason = loop_budget.check_budget(loop_budget.charge(run, tokens=1000))
    assert not ok and "token ceiling" in reason
    ok, reason = loop_budget.check_budget(loop_budget.charge(run, cost_usd=1.0))
    assert not ok and "cost ceiling" in reason


def test_check_budget_unset_optional_ceilings_not_enforced():
    run = loop_budget.new_run("x", 100)  # no token/cost ceilings
    big = loop_budget.charge(run, tokens=10_000_000, cost_usd=999.0)
    ok, _ = loop_budget.check_budget(big)
    assert ok  # only turns gate when the others are None


def test_remaining_reports_only_configured_ceilings():
    run = loop_budget.new_run("x", 5, max_tokens=100)
    rem = loop_budget.remaining(loop_budget.charge(run, turns=2, tokens=30))
    assert rem["turns"] == 3 and rem["tokens"] == 70
    assert "cost_usd" not in rem  # unset → not reported


# --- CLI: arm → status → charge → disarm lifecycle ---

def test_cli_arm_charge_over_budget_and_disarm(tmp_path):
    state = tmp_path / "state"
    # arm with a 2-turn ceiling
    r = _run_cli(BUDGET_PY, ["arm", "--goal", "fix", "--max-turns", "2"], state)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["armed"] is True
    assert (state / loop_common.RUN_STATE_FILE).exists()

    # charge 1/2 → ok (exit 0)
    r = _run_cli(BUDGET_PY, ["charge"], state)
    assert r.returncode == 0 and json.loads(r.stdout)["ok"] is True

    # charge 2/2 → over budget (exit 3)
    r = _run_cli(BUDGET_PY, ["charge"], state)
    assert r.returncode == loop_budget.EXIT_OVER_BUDGET
    assert json.loads(r.stdout)["ok"] is False

    # disarm → run file gone, cost-log appended
    r = _run_cli(BUDGET_PY, ["disarm", "--status", "budget-exhausted"], state)
    assert r.returncode == 0
    assert not (state / loop_common.RUN_STATE_FILE).exists()
    log = (state / loop_common.COST_LOG_FILE).read_text(encoding="utf-8").strip().splitlines()
    assert len(log) == 1
    rec = json.loads(log[0])
    assert rec["final_status"] == "budget-exhausted" and rec["turns"] == 2


def test_cli_double_arm_refused(tmp_path):
    state = tmp_path / "state"
    assert _run_cli(BUDGET_PY, ["arm", "--goal", "a", "--max-turns", "5"], state).returncode == 0
    second = _run_cli(BUDGET_PY, ["arm", "--goal", "b", "--max-turns", "5"], state)
    assert second.returncode == 1 and "already armed" in second.stderr


def test_cli_charge_without_arm_errors(tmp_path):
    r = _run_cli(BUDGET_PY, ["charge"], tmp_path / "state")
    assert r.returncode == 1 and "no armed run" in r.stderr


def test_cli_status_when_idle(tmp_path):
    r = _run_cli(BUDGET_PY, ["status"], tmp_path / "state")
    assert r.returncode == 0 and json.loads(r.stdout)["armed"] is False


# --- ledger: init / parse / append / compact ---

def test_init_ledger_has_all_sections_empty():
    text = loop_ledger.init_ledger("fix CI", "loop-123", updated="2026-06-28T00:00:00+00:00")
    assert "# LOOP-STATE: loop-123" in text
    assert "- **Goal:** fix CI" in text
    sections = loop_ledger.parse_sections(text)
    assert set(sections) == {"Open hypotheses", "Decisions", "Timeline", "Needs-me"}
    assert all(v == [] for v in sections.values())  # placeholders → no real entries


def test_template_matches_init_structure():
    tmpl = (Path(loop_ledger.__file__).parent.parent / "templates" / "LOOP-STATE.md.template").read_text()
    for h in loop_ledger.HEADINGS:
        assert f"## {h}" in tmpl
    assert loop_ledger.PLACEHOLDER in tmpl


def test_append_timeline_adds_dated_bullet_and_updates_header():
    text = loop_ledger.init_ledger("g", "loop-1", updated="2026-06-28T00:00:00+00:00")
    text = loop_ledger.append_entry(text, "finding", "tests fail on import", when="2026-06-28T01:00:00+00:00")
    sections = loop_ledger.parse_sections(text)
    assert sections["Timeline"] == ["- 2026-06-28T01:00:00+00:00 — tests fail on import"]
    assert sections["Open hypotheses"] == []  # placeholder still gone-but-empty elsewhere
    assert "- **Updated:** 2026-06-28T01:00:00+00:00" in text  # header bumped


def test_append_hypothesis_is_a_checkbox():
    text = loop_ledger.init_ledger("g", "loop-1")
    text = loop_ledger.append_entry(text, "hypothesis", "maybe a stale import path")
    assert "- [ ] maybe a stale import path" in loop_ledger.parse_sections(text)["Open hypotheses"]


def test_append_preserves_order_within_section():
    text = loop_ledger.init_ledger("g", "loop-1")
    text = loop_ledger.append_entry(text, "decision", "first", when="2026-06-28T00:00:01+00:00")
    text = loop_ledger.append_entry(text, "decision", "second", when="2026-06-28T00:00:02+00:00")
    decisions = loop_ledger.parse_sections(text)["Decisions"]
    assert decisions == [
        "- 2026-06-28T00:00:01+00:00 — first",
        "- 2026-06-28T00:00:02+00:00 — second",
    ]


def test_append_unknown_section_raises():
    text = loop_ledger.init_ledger("g", "loop-1")
    with pytest.raises(ValueError):
        loop_ledger.append_entry(text, "bogus", "x")


def test_compact_keeps_recent_and_archives_rest():
    text = loop_ledger.init_ledger("g", "loop-1")
    for i in range(5):
        text = loop_ledger.append_entry(text, "timeline", f"event {i}", when=f"2026-06-28T00:00:0{i}+00:00")
    compacted = loop_ledger.compact(text, keep_recent=2)
    timeline = loop_ledger.parse_sections(compacted)["Timeline"]
    assert timeline[0] == "- _(archived 3 earlier entries)_"
    assert timeline[-1] == "- 2026-06-28T00:00:04+00:00 — event 4"
    assert len(timeline) == 3  # marker + 2 kept
    # other sections untouched
    assert loop_ledger.parse_sections(compacted)["Decisions"] == []


def test_compact_idempotent_no_marker_stacking():
    text = loop_ledger.init_ledger("g", "loop-1")
    for i in range(5):
        text = loop_ledger.append_entry(text, "timeline", f"e{i}", when=f"2026-06-28T00:00:0{i}+00:00")
    once = loop_ledger.compact(text, keep_recent=2)
    twice = loop_ledger.compact(once, keep_recent=2)
    markers = [l for l in twice.splitlines() if loop_ledger.ARCHIVE_PREFIX in l]
    assert len(markers) == 1  # not stacked


def test_compact_noop_when_under_threshold():
    text = loop_ledger.init_ledger("g", "loop-1")
    text = loop_ledger.append_entry(text, "timeline", "only one", when="2026-06-28T00:00:00+00:00")
    assert loop_ledger.compact(text, keep_recent=10) == text


def test_ledger_cli_init_append_compact(tmp_path):
    f = tmp_path / "LOOP-STATE.md"
    r = _run_cli(LEDGER_PY, ["init", "--goal", "fix", "--run-id", "loop-9", "--out", str(f)], tmp_path)
    assert r.returncode == 0 and f.exists()
    r = _run_cli(LEDGER_PY, ["append", "--file", str(f), "--section", "needs-me", "--entry", "human review please"], tmp_path)
    assert r.returncode == 0
    assert "- human review please" in loop_ledger.parse_sections(f.read_text())["Needs-me"]
    r = _run_cli(LEDGER_PY, ["compact", "--file", str(f), "--keep", "5"], tmp_path)
    assert r.returncode == 0


# --- safety hook: check_command (pure) ---

def _armed(worktree=None):
    return loop_budget.new_run("g", 10, worktree=worktree)


def test_hook_inert_when_no_run():
    # No armed loop → never blocks, even a push.
    block, _ = loop_hook.check_command("Bash", {"command": "git push origin main"}, None)
    assert block is False


def test_hook_blocks_git_push_when_armed():
    block, reason = loop_hook.check_command("Bash", {"command": "git push origin main"}, _armed())
    assert block is True and "push" in reason


def test_hook_blocks_dangerous_git_in_chained_command():
    block, _ = loop_hook.check_command("Bash", {"command": "pytest -q && git push"}, _armed())
    assert block is True


@pytest.mark.parametrize("cmd", [
    "git merge feature",
    "git rebase main",
    "git reset --hard HEAD~1",
    "git branch -D scratch",
    "git branch --delete old",
    "git worktree remove /tmp/wt",
])
def test_hook_blocks_each_dangerous_git_op(cmd):
    block, _ = loop_hook.check_command("Bash", {"command": cmd}, _armed())
    assert block is True


@pytest.mark.parametrize("cmd", [
    "pytest -q",
    "git status",
    "git commit -m 'draft fix'",   # committing inside the worktree is how a loop drafts
    "git diff",
    "python3 -c 'print(1)'",
])
def test_hook_allows_safe_commands_when_armed(cmd):
    block, _ = loop_hook.check_command("Bash", {"command": cmd}, _armed())
    assert block is False


def test_hook_blocks_write_outside_worktree(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    outside = tmp_path / "elsewhere" / "f.py"
    block, reason = loop_hook.check_command("Write", {"file_path": str(outside)}, _armed(worktree=str(wt)))
    assert block is True and "worktree" in reason


def test_hook_allows_write_inside_worktree(tmp_path):
    wt = tmp_path / "wt"
    wt.mkdir()
    inside = wt / "src" / "f.py"
    block, _ = loop_hook.check_command("Write", {"file_path": str(inside)}, _armed(worktree=str(wt)))
    assert block is False


def test_hook_allows_write_when_no_worktree_set():
    # armed but no worktree → path scoping disabled (git guards still apply)
    block, _ = loop_hook.check_command("Edit", {"file_path": "/anywhere/x.py"}, _armed(worktree=None))
    assert block is False


# --- safety hook: subprocess exit codes ---

def _run_hook(payload: dict, state_dir: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["LOOP_HARNESS_STATE_DIR"] = str(state_dir)
    return subprocess.run(
        [sys.executable, str(HOOK_PY)],
        input=json.dumps(payload), capture_output=True, text=True, env=env,
    )


def test_hook_subprocess_allows_when_idle(tmp_path):
    r = _run_hook({"tool_name": "Bash", "tool_input": {"command": "git push"}}, tmp_path)
    assert r.returncode == 0  # no armed run → allowed


def test_hook_subprocess_blocks_push_when_armed(tmp_path):
    assert _run_cli(BUDGET_PY, ["arm", "--goal", "g", "--max-turns", "5"], tmp_path).returncode == 0
    r = _run_hook({"tool_name": "Bash", "tool_input": {"command": "git push"}}, tmp_path)
    assert r.returncode == 2 and "blocked" in r.stderr


def test_hook_subprocess_allows_safe_when_armed(tmp_path):
    assert _run_cli(BUDGET_PY, ["arm", "--goal", "g", "--max-turns", "5"], tmp_path).returncode == 0
    r = _run_hook({"tool_name": "Bash", "tool_input": {"command": "pytest -q"}}, tmp_path)
    assert r.returncode == 0


def test_hook_subprocess_fails_open_on_bad_stdin(tmp_path):
    env = dict(os.environ)
    env["LOOP_HARNESS_STATE_DIR"] = str(tmp_path)
    r = subprocess.run([sys.executable, str(HOOK_PY)], input="not json", capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "could not parse" in r.stderr


# --- regression: git global-option bypass (qa-gatekeeper REJECT) ---

@pytest.mark.parametrize("cmd", [
    "git -C /repo push",
    "git -c http.x=y push",
    "git --git-dir=/r/.git push",
    "git -C /repo merge x",
    "git -C /repo rebase main",
    "git -C /repo reset --hard HEAD~1",
    "git -C /repo branch -D foo",
    "git -C /repo worktree remove /wt",
    "FOO=bar git push",                       # leading env assignment
    "git --paginate -C /repo push",           # valueless flag + value flag mixed
])
def test_hook_blocks_git_with_global_options(cmd):
    block, _ = loop_hook.check_command("Bash", {"command": cmd}, _armed())
    assert block is True, cmd


@pytest.mark.parametrize("cmd", [
    "git -C /repo status",
    "git -C /repo commit -m wip",   # committing in the worktree is allowed
    "git -C /repo branch newfeature",  # creating a branch is fine
    "git -C /repo worktree add /wt2",
    "echo git push",                  # not actually a git invocation
])
def test_hook_allows_safe_git_with_global_options(cmd):
    block, _ = loop_hook.check_command("Bash", {"command": cmd}, _armed())
    assert block is False, cmd


def test_hook_handles_unbalanced_quotes_without_crashing():
    block, _ = loop_hook.check_command("Bash", {"command": "git -C /r push 'oops"}, _armed())
    assert block is True


# --- regression: corrupt armed-state surfaces a warning, stays inert ---

def test_hook_warns_when_run_state_unreadable(tmp_path):
    (tmp_path / loop_common.RUN_STATE_FILE).write_text("{ not json", encoding="utf-8")
    r = _run_hook({"tool_name": "Bash", "tool_input": {"command": "git push"}}, tmp_path)
    assert r.returncode == 0  # unreadable marker → guards inactive (fail-open), not wedged
    assert "WARNING" in r.stderr and "unreadable" in r.stderr


# --- regression: compaction only strips bullets that ARE archive markers ---

def test_compact_keeps_entry_that_merely_mentions_archive_phrase():
    text = loop_ledger.init_ledger("g", "loop-1")
    text = loop_ledger.append_entry(
        text, "timeline", "note: _(archived earlier) was in the old log", when="2026-06-28T00:00:00+00:00")
    for i in range(3):
        text = loop_ledger.append_entry(text, "timeline", f"e{i}", when=f"2026-06-28T00:00:1{i}+00:00")
    compacted = loop_ledger.compact(text, keep_recent=10)  # under threshold → no archiving
    timeline = loop_ledger.parse_sections(compacted)["Timeline"]
    assert any("mentions the phrase" not in t and "old log" in t for t in timeline)  # entry survived


# --- iteration: ledger status-sync on disarm (dogfood finding #1) ---

def test_set_status_updates_header():
    text = loop_ledger.init_ledger("g", "loop-1", status="armed")
    out = loop_ledger.set_status(text, "converged", updated="2026-06-28T02:00:00+00:00")
    assert "- **Status:** converged" in out
    assert "- **Status:** armed" not in out
    assert "- **Updated:** 2026-06-28T02:00:00+00:00" in out


def test_disarm_syncs_ledger_status(tmp_path):
    state = tmp_path / "state"
    ledger = tmp_path / "LOOP-STATE.md"
    ledger.write_text(loop_ledger.init_ledger("g", "loop-x", status="armed"), encoding="utf-8")
    r = _run_cli(BUDGET_PY, ["arm", "--goal", "g", "--max-turns", "5", "--ledger", str(ledger)], state)
    assert r.returncode == 0
    r = _run_cli(BUDGET_PY, ["disarm", "--status", "converged"], state)
    assert r.returncode == 0 and json.loads(r.stdout)["ledger_synced"] is True
    assert "- **Status:** converged" in ledger.read_text()  # no longer 'armed'


def test_disarm_without_ledger_is_noop(tmp_path):
    state = tmp_path / "state"
    assert _run_cli(BUDGET_PY, ["arm", "--goal", "g", "--max-turns", "5"], state).returncode == 0
    r = _run_cli(BUDGET_PY, ["disarm", "--status", "stopped"], state)
    assert r.returncode == 0 and json.loads(r.stdout)["ledger_synced"] is False


def test_arm_defaults_ledger_to_worktree(tmp_path):
    state = tmp_path / "state"
    wt = tmp_path / "wt"; wt.mkdir()
    ledger = wt / "LOOP-STATE.md"
    ledger.write_text(loop_ledger.init_ledger("g", "loop-y"), encoding="utf-8")
    assert _run_cli(BUDGET_PY, ["arm", "--goal", "g", "--max-turns", "5", "--worktree", str(wt)], state).returncode == 0
    r = _run_cli(BUDGET_PY, ["disarm", "--status", "converged"], state)
    assert json.loads(r.stdout)["ledger_synced"] is True  # found <worktree>/LOOP-STATE.md by convention
    assert "- **Status:** converged" in ledger.read_text()


# --- iteration: loop_logscan summarizer (dogfood finding #2) ---

def test_logscan_parses_failure_summary():
    out = loop_logscan.summarize("1 failed, 59 passed in 0.50s")
    assert out["failed"] == 1 and out["passed"] == 59 and out["ok"] is False and out["matched"] is True


def test_logscan_parses_green_summary():
    out = loop_logscan.summarize("324 passed, 2 skipped in 2.32s")
    assert out["ok"] is True and out["passed"] == 324 and out["skipped"] == 2 and out["failed"] == 0


def test_logscan_extracts_failing_nodes():
    text = "FAILED tests/test_x.py::test_a - AssertionError\nFAILED tests/test_x.py::test_b - ValueError\n1 failed, 1 passed"
    out = loop_logscan.summarize(text)
    assert out["failing_tests"] == ["tests/test_x.py::test_a", "tests/test_x.py::test_b"]


def test_logscan_counts_errors_as_not_ok():
    out = loop_logscan.summarize("2 errors, 10 passed in 1s")
    assert out["errors"] == 2 and out["ok"] is False


def test_logscan_unparseable_is_not_ok():
    out = loop_logscan.summarize("......... [100%]")  # raw progress, no summary
    assert out["matched"] is False and out["ok"] is False


def test_logscan_strips_ansi_color():
    out = loop_logscan.summarize("\x1b[31m1 failed\x1b[0m, \x1b[32m2 passed\x1b[0m in 0.1s")
    assert out["failed"] == 1 and out["passed"] == 2


def test_logscan_cli_reads_stdin(tmp_path):
    env = dict(os.environ)
    r = subprocess.run([sys.executable, str(LOGSCAN_PY)], input="3 failed, 7 passed in 1s",
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and json.loads(r.stdout)["failed"] == 3
