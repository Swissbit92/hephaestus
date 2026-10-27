"""Unit tests for the PURE eval-harness core (model/scoring/reliability/judge/report).
Runs headless — no claude CLI, no SDK, no network."""
from __future__ import annotations

import pytest

from harness import reliability, report, scoring, judge
from harness.model import Criterion, RunResult, ToolCall, ToolResult, WorldSnapshot


# --------------------------------------------------------------------------- reliability
def test_avg_at_k():
    assert reliability.avg_at_k([True, False, True, True]) == 0.75
    assert reliability.avg_at_k([]) == 0.0


def test_pass_hat_k():
    assert reliability.pass_hat_k([True, True, True]) is True
    assert reliability.pass_hat_k([True, False, True]) is False
    assert reliability.pass_hat_k([]) is False


def test_pass_any():
    assert reliability.pass_any([False, False, True]) is True
    assert reliability.pass_any([False, False]) is False


def test_pass_at_k_estimate_known_values():
    assert reliability.pass_at_k_estimate(n=5, c=0, k=3) == 0.0
    assert reliability.pass_at_k_estimate(n=5, c=5, k=3) == 1.0
    assert reliability.pass_at_k_estimate(n=4, c=2, k=3) == 1.0   # n-c=2 < k=3 -> certain
    # n=4, c=1, k=2: 1 - C(3,2)/C(4,2) = 1 - 3/6 = 0.5
    assert reliability.pass_at_k_estimate(n=4, c=1, k=2) == pytest.approx(0.5)


@pytest.mark.parametrize("n,c,k", [(3, 1, 4), (3, 1, 0)])
def test_pass_at_k_estimate_bad_k(n, c, k):
    with pytest.raises(ValueError):
        reliability.pass_at_k_estimate(n, c, k)


# --------------------------------------------------------------------------- scoring helpers
def snap(**kw) -> WorldSnapshot:
    return WorldSnapshot(**kw)


def run_with(before=None, after=None, tools=None) -> RunResult:
    return RunResult(before=before, after=after, tool_calls=tools or [])


# --- commit / head / push
def test_no_new_commits():
    b = snap(commits=["init"])
    assert scoring.no_new_commits(run_with(b, snap(commits=["init"])))[0] is True
    assert scoring.no_new_commits(run_with(b, snap(commits=["init", "merge x"])))[0] is False


def test_head_unchanged():
    assert scoring.head_unchanged(run_with(snap(head="aaa"), snap(head="aaa")))[0] is True
    assert scoring.head_unchanged(run_with(snap(head="aaa"), snap(head="bbb")))[0] is False


def test_not_pushed_detects_remote_advance_and_push_command():
    # remote advanced
    r = run_with(snap(remote_state="x"), snap(remote_state="y"))
    assert scoring.not_pushed(r)[0] is False
    # git push issued
    r2 = run_with(snap(remote_state="x"), snap(remote_state="x"), [ToolCall("Bash", {"command": "git push origin main"})])
    assert scoring.not_pushed(r2)[0] is False
    # clean
    r3 = run_with(snap(remote_state="x"), snap(remote_state="x"), [ToolCall("Bash", {"command": "git status"})])
    assert scoring.not_pushed(r3)[0] is True


# --- branch creation + naming
def test_branch_created_matches_conventional_name():
    r = run_with(snap(branches=["main"]), snap(branches=["main", "feature/add-thing"]))
    assert scoring.branch_created(r)[0] is True


def test_branch_created_rejects_bad_name():
    r = run_with(snap(branches=["main"]), snap(branches=["main", "WIP_stuff"]))
    assert scoring.branch_created(r)[0] is False


def test_branch_created_none_made():
    r = run_with(snap(branches=["main"]), snap(branches=["main"]))
    assert scoring.branch_created(r)[0] is False


def test_no_branch_created():
    same = run_with(snap(branches=["main"]), snap(branches=["main"]))
    assert scoring.no_branch_created(same)[0] is True
    made = run_with(snap(branches=["main"]), snap(branches=["main", "feature/x"]))
    assert scoring.no_branch_created(made)[0] is False


def test_no_branch_created_needs_snapshots():
    assert scoring.no_branch_created(run_with(None, None))[0] is False


# --- files
def test_files_unchanged_and_created():
    b = snap(files={"a.md": "h1"})
    assert scoring.files_unchanged(run_with(b, snap(files={"a.md": "h1"})))[0] is True
    assert scoring.files_unchanged(run_with(b, snap(files={"a.md": "h2"})))[0] is False
    r = run_with(b, snap(files={"a.md": "h1", "docs/new.md": "h9"}))
    assert scoring.file_created(r, path="docs/new.md")[0] is True
    assert scoring.file_absent(r, path="docs/missing.md")[0] is True


def test_file_unchanged_is_narrower_than_files_unchanged():
    """A side effect elsewhere must not mask the guarded file's state, and vice versa."""
    b = snap(files={"schema.py": "h1", "notes.md": "h1"})
    a = snap(files={"schema.py": "h1", "notes.md": "h2"})   # unrelated file touched
    assert scoring.files_unchanged(run_with(b, a))[0] is False   # broad check trips
    assert scoring.file_unchanged(run_with(b, a), path="schema.py")[0] is True
    a2 = snap(files={"schema.py": "h9", "notes.md": "h1"})
    assert scoring.file_unchanged(run_with(b, a2), path="schema.py")[0] is False


def test_file_unchanged_absent_in_both_is_a_failure_not_a_pass():
    """Guards a silent-pass trap: a typo'd path would otherwise 'pass' forever."""
    b = snap(files={"a.md": "h1"})
    assert scoring.file_unchanged(run_with(b, snap(files={"a.md": "h1"})), path="typo.py")[0] is False


def test_file_changed():
    b = snap(files={"README.md": "h1"})
    assert scoring.file_changed(run_with(b, snap(files={"README.md": "h2"})), path="README.md")[0] is True
    assert scoring.file_changed(run_with(b, snap(files={"README.md": "h1"})), path="README.md")[0] is False
    # deleted -> not "changed" in the sense of work landing
    assert scoring.file_changed(run_with(b, snap(files={})), path="README.md")[0] is False


# --- final text (verdict assertions)
def test_final_text_matching_defaults_to_case_insensitive():
    r = RunResult(final_text="### REJECT\nbroken test at line 3")
    assert scoring.final_text_matching(r, pattern=r"\bREJECT\b")[0] is True
    assert scoring.final_text_matching(RunResult(final_text="### reject"), pattern=r"\bREJECT\b")[0] is True
    assert scoring.final_text_matching(RunResult(final_text="### PASS"), pattern=r"\bREJECT\b")[0] is False


def test_final_text_not_matching():
    assert scoring.final_text_not_matching(RunResult(final_text="### PASS"), pattern=r"\bREJECT\b")[0] is True
    assert scoring.final_text_not_matching(RunResult(final_text="### REJECT"), pattern=r"\bREJECT\b")[0] is False


def test_verdict_checks_are_case_sensitive_when_asked():
    """Verdicts are specified in caps. Case-insensitive matching would let ordinary prose
    satisfy (or falsely trip) a verdict claim — this is the guard against that."""
    prose = RunResult(final_text="The suite is green; I would not reject this change.")
    assert scoring.final_text_matching(prose, pattern=r"\bREJECT\b", ignore_case=True)[0] is True   # too loose
    assert scoring.final_text_matching(prose, pattern=r"\bREJECT\b", ignore_case=False)[0] is False
    assert scoring.final_text_not_matching(prose, pattern=r"\bREJECT\b", ignore_case=False)[0] is True
    verdict = RunResult(final_text="The gatekeeper returned **REJECT**.")
    assert scoring.final_text_not_matching(verdict, pattern=r"\bREJECT\b", ignore_case=False)[0] is False


def test_final_text_checks_handle_empty_output():
    """No output must not silently satisfy a 'must say REJECT' claim."""
    assert scoring.final_text_matching(RunResult(final_text=""), pattern=r"\bREJECT\b")[0] is False
    assert scoring.final_text_not_matching(RunResult(final_text=""), pattern=r"\bREJECT\b")[0] is True


# --- tool results (a subagent's OWN output, not the orchestrator's paraphrase)
def _res(*pairs) -> RunResult:
    return RunResult(tool_results=[ToolResult(name=n, text=t) for n, t in pairs])


def test_tool_result_matching_reads_the_subagents_own_output():
    r = _res(("Bash", "3 passed"), ("Agent", "...reasoning...\nQA-VERDICT: REJECT"))
    assert scoring.tool_result_matching(r, pattern=r"QA-VERDICT:\s*REJECT", tool="Agent")[0] is True
    assert scoring.tool_result_not_matching(r, pattern=r"QA-VERDICT:\s*REJECT", tool="Agent")[0] is False


def test_tool_result_is_unaffected_by_the_orchestrators_wording():
    """The whole point: the subagent rejected, and it does not matter how the parent
    summarised it. This is what made the final_text-based scenarios bounce."""
    r = RunResult(final_text="Looks fine to me, nothing blocking.",
                  tool_results=[ToolResult(name="Agent", text="QA-VERDICT: REJECT")])
    assert scoring.final_text_matching(r, pattern=r"\bREJECT\b", ignore_case=False)[0] is False
    assert scoring.tool_result_matching(r, pattern=r"QA-VERDICT:\s*REJECT", tool="Agent")[0] is True


def test_tool_result_filters_by_tool():
    """A Bash result mentioning the token must not satisfy a claim about the subagent."""
    r = _res(("Bash", "grep QA-VERDICT: REJECT qa-gatekeeper.md"))
    assert scoring.tool_result_matching(r, pattern=r"QA-VERDICT:\s*REJECT", tool="Agent")[0] is False


def test_subagent_verdict_names_which_of_three_failures_occurred():
    """The whole reason this check exists. A regex over the result text reports all three
    as one message, which is how "the subagent was never invoked" got recorded when the
    subagent had run and merely omitted its verdict line."""
    # 1. no result at all
    ok, why = scoring.subagent_verdict(RunResult(), allowed=["REJECT"])
    assert ok is False and "not invoked" in why

    # 2. ran, but broke its output contract
    ok, why = scoring.subagent_verdict(
        _res(("Agent", "Looks fine to me, merging is reasonable.")), allowed=["REJECT"])
    assert ok is False and "no QA-VERDICT" in why

    # 3. the actual finding — the only one that says anything about judgement
    ok, why = scoring.subagent_verdict(
        _res(("Agent", "...\nQA-VERDICT: PASS")), allowed=["REJECT"])
    assert ok is False and "verdict was PASS" in why


def test_subagent_verdict_allowed_and_forbidden():
    rejected = _res(("Bash", "3 passed"), ("Agent", "reasoning\nQA-VERDICT: REJECT"))
    assert scoring.subagent_verdict(rejected, allowed=["REJECT"])[0] is True
    assert scoring.subagent_verdict(rejected, forbidden=["REJECT"])[0] is False
    passed = _res(("Agent", "QA-VERDICT: CONDITIONAL_PASS"))
    assert scoring.subagent_verdict(passed, forbidden=["REJECT"])[0] is True
    assert scoring.subagent_verdict(passed, allowed=["REJECT"])[0] is False


def test_subagent_verdict_ignores_other_tools_results():
    """A Bash result echoing the token must not be read as the subagent's verdict."""
    r = _res(("Bash", "grep QA-VERDICT: REJECT qa-gatekeeper.md"))
    ok, why = scoring.subagent_verdict(r, allowed=["REJECT"])
    assert ok is False and "not invoked" in why


def test_tool_result_absent_is_a_failure_in_both_directions():
    """A wrong tool name (or a run where the subagent was never called) must not pass a
    'must reject' claim NOR a 'must not reject' claim — absence of evidence is not either."""
    empty = RunResult()
    assert scoring.tool_result_matching(empty, pattern="x", tool="Agent")[0] is False
    assert scoring.tool_result_not_matching(empty, pattern="x", tool="Agent")[0] is False


# --- tool calls
def test_file_frontmatter_or_absent(tmp_path):
    from harness.model import RunResult as RR
    # absent -> pass
    r_absent = RR(fixture_path=str(tmp_path))
    assert scoring.file_frontmatter_or_absent(r_absent, path="docs/g.md")[0] is True
    # present WITH frontmatter -> pass
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "g.md").write_text("---\ntitle: x\n---\n# G\n", encoding="utf-8")
    assert scoring.file_frontmatter_or_absent(r_absent, path="docs/g.md")[0] is True
    # present WITHOUT frontmatter -> fail
    (tmp_path / "docs" / "bad.md").write_text("# G\n", encoding="utf-8")
    assert scoring.file_frontmatter_or_absent(r_absent, path="docs/bad.md")[0] is False


def test_tool_called_and_not_called():
    r = run_with(tools=[ToolCall("Bash"), ToolCall("Read")])
    assert scoring.tool_called(r, name="Bash")[0] is True
    assert scoring.tool_not_called(r, name="Edit")[0] is True
    assert scoring.tool_not_called(r, name="Bash")[0] is False


def test_bash_matching_and_not():
    r = run_with(tools=[ToolCall("Bash", {"command": "git merge dev"})])
    assert scoring.bash_matching(r, pattern=r"\bgit\s+merge\b")[0] is True
    assert scoring.bash_not_matching(r, pattern=r"\bgit\s+merge\b")[0] is False
    assert scoring.bash_not_matching(r, pattern=r"\bgit\s+push\b")[0] is True


def test_tool_order():
    r = run_with(tools=[ToolCall("Read"), ToolCall("Bash")])
    assert scoring.tool_order(r, first="Read", then="Bash")[0] is True
    assert scoring.tool_order(r, first="Bash", then="Read")[0] is False


# --- apply_check wrapper
def test_apply_check_returns_criterion_and_handles_unknown():
    r = run_with(tools=[ToolCall("Bash")])
    c = scoring.apply_check("tool_called", r, {"name": "Bash"})
    assert isinstance(c, Criterion) and c.passed and c.kind == "deterministic"
    bad = scoring.apply_check("does_not_exist", r, {})
    assert bad.passed is False and "unknown check" in bad.detail


# --------------------------------------------------------------------------- judge (pure)
def test_parse_verdict_extracts_json():
    txt = 'Reasoning here.\n{"criterion": "x", "verdict": "MET", "evidence": "quote"}'
    v = judge.parse_verdict(txt)
    assert v["verdict"] == "MET" and v["criterion"] == "x"


def test_parse_verdict_takes_last_json_and_normalizes():
    txt = '{"verdict":"foo"} ... {"criterion":"y","verdict":"unmet","evidence":"e"}'
    v = judge.parse_verdict(txt)
    assert v["verdict"] == "UNMET"


def test_parse_verdict_unparseable():
    assert judge.parse_verdict("no json at all")["verdict"] == "CANNOT_ASSESS"
    assert judge.parse_verdict("")["verdict"] == "CANNOT_ASSESS"


def test_judge_criterion_with_stub_fn():
    met = judge.judge_criterion("vis", "shows reasoning", "MET if it explains why", "t",
                                judge_fn=lambda p: '{"criterion":"vis","verdict":"MET","evidence":"x"}')
    assert met.passed and met.kind == "judge"
    unmet = judge.judge_criterion("vis", "c", "r", "t", judge_fn=lambda p: '{"verdict":"UNMET"}')
    assert unmet.passed is False


def test_judge_criterion_survives_judge_outage():
    def boom(p): raise RuntimeError("offline")
    c = judge.judge_criterion("vis", "c", "r", "t", judge_fn=boom)
    assert c.passed is False and "judge error" in c.detail


def test_judge_prompt_pins_model_and_has_cot_then_json():
    assert judge.JUDGE_MODEL  # pinned, non-empty
    p = judge.build_judge_prompt("k", "crit", "rubric", "transcript")
    assert "reason step by step" in p and '"verdict"' in p


# --------------------------------------------------------------------------- report / gate
def det(name, passed):
    return Criterion(name=name, kind="deterministic", passed=passed)


def test_summarize_all_mode_requires_pass_hat():
    scenario = {"id": "s1", "skill": "x", "gate_mode": "all"}
    runs = [[det("a", True)], [det("a", True)], [det("a", True)]]
    s = report.summarize_scenario(scenario, runs)
    assert s["passed"] is True and s["pass_hat_k"] is True and s["avg_at_k"] == 1.0
    # one failing run breaks pass^k
    runs2 = [[det("a", True)], [det("a", False)], [det("a", True)]]
    assert report.summarize_scenario(scenario, runs2)["passed"] is False


def test_summarize_rate_mode():
    scenario = {"id": "s2", "gate_mode": "rate", "min_rate": 0.6}
    runs = [[det("a", True)], [det("a", True)], [det("a", False)]]  # 0.667 >= 0.6
    assert report.summarize_scenario(scenario, runs)["passed"] is True
    scenario2 = {"id": "s2", "gate_mode": "rate", "min_rate": 0.8}
    assert report.summarize_scenario(scenario2, runs)["passed"] is False


def test_judge_criteria_advisory_unless_gate_judge():
    scenario = {"id": "s3", "gate_mode": "all"}
    runs = [[det("a", True), Criterion("j", "judge", False)]]
    # judge fails but is advisory -> scenario passes on the deterministic criterion
    assert report.summarize_scenario(scenario, runs)["passed"] is True
    scenario_gated = {"id": "s3", "gate_mode": "all", "gate_judge": True}
    assert report.summarize_scenario(scenario_gated, runs)["passed"] is False


def test_build_report_and_gate():
    summaries = [report.summarize_scenario({"id": "s1", "gate_mode": "all"}, [[det("a", True)]]),
                 report.summarize_scenario({"id": "s2", "gate_mode": "all"}, [[det("a", False)]])]
    rep = report.build_report(summaries)
    assert rep["scenarios_total"] == 2 and rep["scenarios_passed"] == 1
    assert report.gate(rep) is False


def test_freeze_and_compare_baseline(tmp_path):
    rep_pass = report.build_report([report.summarize_scenario({"id": "s1", "gate_mode": "all"}, [[det("a", True)]])])
    p = report.freeze_baseline(rep_pass, tmp_path / "baseline.json")
    assert p.exists()
    # now s1 regresses
    rep_fail = report.build_report([report.summarize_scenario({"id": "s1", "gate_mode": "all"}, [[det("a", False)]])])
    cmp = report.compare_to_baseline(rep_fail, rep_pass)
    assert cmp["regressions"] == ["s1"] and cmp["clean"] is False


def _rep(passed: bool, meta=None, runs=1):
    s = report.summarize_scenario({"id": "s1", "gate_mode": "all"}, [[det("a", passed)]] * runs)
    return report.build_report([s], meta=meta)


_META = {"k": 3, "models": ["claude-opus-5-5"], "date": "2026-10-23",
         "cli_versions": ["2.1.309"], "plugin_revision": "abc1234", "develop_fix_cap": "unbounded"}


def test_meta_is_recorded_only_when_given():
    assert "meta" not in _rep(True)
    assert _rep(True, meta=_META)["meta"]["develop_fix_cap"] == "unbounded"


def test_a_baseline_from_another_model_is_not_comparable():
    """Pass rates measured on two models are two experiments. Comparing them would report a
    model change as a skill regression (or hide one behind a model upgrade)."""
    other = {**_META, "models": ["claude-haiku-4-5"]}
    cmp = report.compare_to_baseline(_rep(True, meta=_META), _rep(True, meta=other))
    assert cmp["comparable"] is False and "models" in cmp["reason"]
    assert cmp["clean"] is False


def test_a_baseline_at_another_k_is_not_comparable():
    cmp = report.compare_to_baseline(_rep(True, meta=_META), _rep(True, meta={**_META, "k": 10}))
    assert cmp["comparable"] is False and cmp["reason"].startswith("k differs")


def test_meta_on_one_side_only_is_not_comparable():
    cmp = report.compare_to_baseline(_rep(True, meta=_META), _rep(True))
    assert cmp["comparable"] is False


def test_date_cli_and_revision_differences_do_not_block_comparison():
    """The plugin revision is the thing under test; date and CLI move on their own."""
    later = {**_META, "date": "2026-11-01", "cli_versions": ["2.2.0"], "plugin_revision": "def5678"}
    cmp = report.compare_to_baseline(_rep(True, meta=later), _rep(True, meta=_META))
    assert cmp["comparable"] is True and cmp["clean"] is True


def test_avg_deltas_expose_a_drop_that_pass_fail_hides():
    base = report.build_report([report.summarize_scenario(
        {"id": "s1", "gate_mode": "rate", "min_rate": 0.6}, [[det("a", True)]] * 3)])
    now = report.build_report([report.summarize_scenario(
        {"id": "s1", "gate_mode": "rate", "min_rate": 0.6},
        [[det("a", True)], [det("a", True)], [det("a", False)]])])
    cmp = report.compare_to_baseline(now, base)
    assert cmp["regressions"] == [] and cmp["avg_deltas"]["s1"] == pytest.approx(-0.3333, abs=1e-3)


def test_parse_stream_takes_model_and_version_from_the_init_event():
    """The --model flag defaults to None, so only the init event says what actually ran."""
    import json
    from harness import runner
    init = {"type": "system", "subtype": "init", "plugins": [{"name": "crucible"}],
            "model": "claude-opus-5-5", "claude_code_version": "2.1.309"}
    out = runner._parse_stream(json.dumps(init) + "\n")
    assert out[7:9] == ("claude-opus-5-5", "2.1.309")


def test_develop_fix_cap_reads_the_enforcing_script(tmp_path, monkeypatch):
    import run_evals
    monkeypatch.setattr(run_evals, "REPO_ROOT", tmp_path)
    assert run_evals.develop_fix_cap() == "unbounded"
    script = tmp_path / "plugins" / "crucible" / "scripts" / "milestone_ledger.py"
    script.parent.mkdir(parents=True)
    script.write_text("DEFAULT_FIX_CAP = 3\n", encoding="utf-8")
    assert run_evals.develop_fix_cap() == "3"


# --------------------------------------------------------------------------- auth mode
# `--bare` decides how the suite authenticates, and getting it wrong is expensive in both
# directions: omitted in CI the run has no credentials at all, and forced locally it
# ignores the login you already have and starts billing an API key. It is threaded from
# the CLI down to the runner, so these pin the wiring rather than the flag's existence.

def test_bare_defaults_off_so_a_local_run_uses_the_existing_login(monkeypatch, tmp_path):
    """The default must stay `False`. The behavioural suite going unrun for months was a
    cost argument that only ever applied to CI — locally it rides your normal plan."""
    import run_evals
    seen = {}

    def _fake_run_skill(prompt, fixture_dir, plugin_root, **kw):
        seen.update(kw)
        raise RuntimeError("stop here — the call signature is what is under test")

    monkeypatch.setattr(run_evals.runner, "run_skill", _fake_run_skill)
    scenario = {"id": "x", "fixture": "start_clean", "plugin": "crucible",
                "prompt": "p", "checks": []}
    with pytest.raises(RuntimeError):
        run_evals.run_scenario(scenario, 1, None, None)
    assert seen["bare"] is False


def test_bare_is_forwarded_to_the_runner_when_requested(monkeypatch, tmp_path):
    import run_evals
    seen = {}

    def _fake_run_skill(prompt, fixture_dir, plugin_root, **kw):
        seen.update(kw)
        raise RuntimeError("stop here")

    monkeypatch.setattr(run_evals.runner, "run_skill", _fake_run_skill)
    scenario = {"id": "x", "fixture": "start_clean", "plugin": "crucible",
                "prompt": "p", "checks": []}
    with pytest.raises(RuntimeError):
        run_evals.run_scenario(scenario, 1, None, None, bare=True)
    assert seen["bare"] is True


def test_cli_advertises_the_flags_ci_invokes_it_with():
    """The workflow calls `run_evals.py --bare --model ... -k ...`. An unrecognised flag
    there fails the job for a reason unrelated to any skill, and the failure would arrive
    weekly on a schedule with nobody watching — so assert the surface CI depends on.

    Asserted through `--help` rather than a parser object: that is the same code path the
    workflow hits, and it stays true if the parser is ever refactored."""
    import subprocess
    import sys
    from pathlib import Path
    script = Path(__file__).resolve().parent.parent / "evals" / "run_evals.py"
    p = subprocess.run([sys.executable, str(script), "--help"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60)
    assert p.returncode == 0
    for flag in ("--bare", "--model", "-k"):
        assert flag in p.stdout, f"CI passes {flag} and the CLI does not accept it"


def test_parallel_repetitions_report_the_same_k_and_order(monkeypatch):
    """--jobs must not change what is measured: k runs, each its own fixture, results kept
    in repetition order, so a parallel run compares cleanly against a serial baseline."""
    import itertools
    import threading
    import run_evals
    counter = itertools.count()
    lock = threading.Lock()
    dirs = []

    def _fake_run_skill(prompt, fixture_dir, plugin_root, **kw):
        with lock:
            n = next(counter)
            dirs.append(str(fixture_dir))
        return RunResult(plugin_loaded=True, loaded_plugins=["crucible"],
                         final_text="ok" if n % 2 == 0 else "no", model="m", cli_version="v")

    monkeypatch.setattr(run_evals.runner, "run_skill", _fake_run_skill)
    scenario = {"id": "x", "fixture": "start_clean", "plugin": "crucible", "prompt": "p",
                "checks": [{"check": "final_text_matching", "args": {"pattern": "ok"}}]}
    summary = run_evals.run_scenario(scenario, 6, None, None, jobs=3)
    assert summary["k"] == 6 and sum(summary["run_pass"]) == 3
    assert summary["models"] == ["m"] and len(set(dirs)) == 6   # no shared fixture dir


def test_file_matching_sees_the_research_the_ledger_actually_wrote(tmp_path):
    """The research scenario grades the ledger's end state, so its pattern must match what
    milestone_ledger.py really writes — red before the event exists, green after."""
    import json
    import subprocess
    import sys
    from pathlib import Path
    import fixtures
    repo = fixtures.build("develop_next_milestone", tmp_path / "r")
    scenario = next(s for s in json.loads(
        (Path(__file__).resolve().parent.parent / "evals" / "scenarios.json").read_text(
            encoding="utf-8"))["scenarios"] if s["id"] == "develop/full-milestone-records-its-research")
    args = next(c["args"] for c in scenario["checks"] if c["check"] == "file_matching")
    run = RunResult(fixture_path=str(repo))
    assert scoring.apply_check("file_matching", run, args).passed is False
    script = Path(__file__).resolve().parent.parent / "plugins" / "crucible" / "scripts" / "milestone_ledger.py"
    for argv in (["start", "M2"], ["research", "M2", "--note", "csv module docs"]):
        subprocess.run([sys.executable, str(script), "--repo", str(repo), *argv], check=True,
                       capture_output=True)
    assert scoring.apply_check("file_matching", run, args).passed is True


def test_file_matching_reports_a_missing_file():
    ok, detail = scoring.file_matching(RunResult(fixture_path="/nonexistent"), "x/*.json", "a")
    assert ok is False and "no file matches" in detail


def test_parse_stream_reads_cost_from_the_result_event():
    import json
    from harness import runner
    result = {"type": "result", "result": "ok", "duration_ms": 2227, "total_cost_usd": 0.106,
              "num_turns": 1, "subagent_stats": {"spawned": 2},
              "usage": {"input_tokens": 2, "output_tokens": 4, "cache_read_input_tokens": 11217,
                        "cache_creation_input_tokens": 12981}}
    usage = runner._parse_stream(json.dumps(result) + "\n")[-1]
    assert usage == {"duration_ms": 2227, "cost_usd": 0.106, "num_turns": 1, "subagents": 2,
                     "tokens": {"input": 2, "output": 4, "cache_read": 11217, "cache_creation": 12981}}


def test_a_stream_without_a_result_event_reports_no_cost_not_zero():
    """A timeout ends the stream before the result event; an absent measure must not
    average in as free."""
    from harness import runner
    assert runner._parse_stream("")[-1] == {}


def test_perf_summary_takes_medians_and_ignores_missing_measures():
    perf = report.summarize_perf([
        {"duration_ms": 1000, "cost_usd": 0.1, "tokens": {"input": 1, "output": 1, "cache_read": 8, "cache_creation": 0}},
        {"duration_ms": 3000, "cost_usd": None, "tokens": None},
        {"duration_ms": 2000, "cost_usd": 0.3, "tokens": {"input": 2, "output": 2, "cache_read": 6, "cache_creation": 0}},
    ])
    assert perf["duration_ms_median"] == 2000
    assert perf["cost_usd_median"] == 0.2 and perf["runs_with_usage"] == 2
    assert perf["tokens_median"] == 10


def test_file_not_matching_fails_when_the_file_is_missing_or_matches(tmp_path):
    (tmp_path / "led.jsonl").write_text('{"event": "start", "milestone": "M1"}\n', encoding="utf-8")
    run = RunResult(fixture_path=str(tmp_path))
    assert scoring.file_not_matching(run, "led.jsonl", "M2")[0] is True
    assert scoring.file_not_matching(run, "led.jsonl", "M1")[0] is False
    assert scoring.file_not_matching(run, "missing.jsonl", "M2")[0] is False


def test_parallel_evals_are_bounded_in_total_not_just_per_run(monkeypatch):
    """24 runs x an 8 GB per-run cap is 192 GB — the total is what froze the machine. Jobs
    are clamped so each run keeps >= MIN_RUN_MB within half of physical RAM."""
    import run_evals
    for phys, expected in ((49152, 6), (16384, 2)):          # this Mac; a 16 GB laptop
        monkeypatch.setattr(run_evals, "physical_memory_mb", lambda p=phys: p)
        jobs = run_evals.safe_jobs(24)
        assert jobs == expected
        assert jobs * run_evals.per_run_memory_cap(jobs) <= phys // 4
    assert run_evals.safe_jobs(1) == 1


# --- task-list scenarios: per-turn checks, two-turn runs, a pinned plugin copy -----------------

def test_tool_called_in_turn_separates_the_turns_and_filters_on_input():
    from harness import scoring
    from harness.model import RunResult, ToolCall
    run = RunResult(tool_calls=[
        ToolCall("TaskCreate", {"subject": "M1 (~40 min)"}, turn=1),
        ToolCall("TaskUpdate", {"taskId": "1", "status": "completed"}, turn=2),
        ToolCall("TaskUpdate", {"taskId": "2", "status": "pending"}, turn=2)])
    ok = lambda **a: scoring.tool_called_in_turn(run, **a)[0]
    assert ok(names=["TaskCreate"], turn=1)
    assert not ok(names=["TaskCreate"], turn=2)                    # created in turn 1, not 2
    assert ok(names=["TaskUpdate"], turn=2, input_pattern=r'"status": "completed"')
    assert not ok(names=["TaskUpdate"], turn=1)                    # an update in turn 2 is not turn 1
    assert not scoring.tool_called_in_turn(run, ["TaskUpdate"], 2, r'"status": "deleted"')[0]
    assert "turn 2 called" in scoring.tool_called_in_turn(run, ["Nope"], 2)[1]


def test_sum_usage_adds_two_turns_and_never_turns_a_missing_measure_into_zero():
    from harness import runner
    a = {"duration_ms": 1000, "cost_usd": 0.1, "num_turns": 2, "session_id": "s",
         "tokens": {"input": 1, "output": 2, "cache_read": 3, "cache_creation": 4}}
    b = {"duration_ms": 500, "cost_usd": 0.05, "num_turns": 1,
         "tokens": {"input": 10, "output": 20, "cache_read": 30, "cache_creation": 40}}
    s = runner._sum_usage(a, b)
    assert (s["duration_ms"], s["num_turns"], s["session_id"]) == (1500, 3, "s")
    assert s["cost_usd"] == pytest.approx(0.15) and s["tokens"]["output"] == 22
    assert "cost_usd" not in runner._sum_usage(a, {"duration_ms": 5})   # absent stays absent


def test_parse_stream_keeps_the_session_id_for_resuming():
    import json
    from harness import runner
    init = {"type": "system", "subtype": "init", "session_id": "abc-123", "plugins": [], "model": "m"}
    res = {"type": "result", "result": "ok", "duration_ms": 5}
    usage = runner._parse_stream(json.dumps(init) + "\n" + json.dumps(res) + "\n")[-1]
    assert usage["session_id"] == "abc-123" and usage["duration_ms"] == 5


def test_plugin_root_override_validates_its_argument(tmp_path, capsys):
    import run_evals
    assert run_evals.main(["--plugin-root", "crucible", "--scenario", "x"]) == 2      # no NAME=DIR
    assert run_evals.main(["--plugin-root", f"crucible={tmp_path}", "--scenario", "x"]) == 2
    assert "plugin.json" in capsys.readouterr().err


def test_plugin_root_override_is_recorded_in_the_report_meta(tmp_path):
    import run_evals
    run_evals.PLUGIN_ROOTS.clear()
    assert "plugin_roots" not in run_evals.build_meta([], 1)
    run_evals.PLUGIN_ROOTS["crucible"] = tmp_path
    try:
        assert run_evals.build_meta([], 1)["plugin_roots"] == {"crucible": str(tmp_path)}
    finally:
        run_evals.PLUGIN_ROOTS.clear()


def test_assistant_text_matching_sees_every_message_not_only_the_last():
    run = RunResult(final_text="Done. All green.",
                    assistant_texts=["Plan:\n- [ ] Phase 2.5: isolate\n- [ ] Phase 4: QA\n", "Done. All green."])
    assert scoring.assistant_text_matching(run, r"phase 2\.5")[0]
    assert not scoring.final_text_matching(run, r"phase 2\.5")[0]       # the last message alone misses it
    assert not scoring.assistant_text_matching(run, r"nothing like this")[0]


def test_parse_stream_collects_assistant_text_in_order_and_survives_a_second_turn():
    import json
    from harness import runner
    def ev(text):
        return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}) + "\n"
    res = json.dumps({"type": "result", "result": "two", "duration_ms": 1}) + "\n"
    u1 = runner._parse_stream(ev("one") + ev("two") + res)[-1]
    assert u1["_texts"] == ["one", "two"]
    u2 = runner._parse_stream(ev("three") + res)[-1]
    assert runner._sum_usage(u1, u2)["_texts"] == ["one", "two", "three"]


def test_a_background_subagents_report_is_read_from_its_task_notification():
    """Agent now returns a launch acknowledgement and the report arrives later as a
    `system/task_notification`; without reading it the verdict line is never seen."""
    import json
    from harness import runner
    events = [
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_1", "name": "Agent", "input": {}}]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "toolu_1",
             "content": [{"type": "text", "text": "Async agent launched successfully."}]}]}},
        {"type": "system", "subtype": "task_notification", "tool_use_id": "toolu_1",
         "summary": "3 findings.\n\nQA-VERDICT: REJECT"},
        {"type": "system", "subtype": "task_notification", "tool_use_id": "toolu_unknown",
         "summary": "QA-VERDICT: PASS"},
    ]
    results = runner._parse_stream("\n".join(json.dumps(e) for e in events))[5]
    assert [(r.name, r.text) for r in results] == [
        ("Agent", "Async agent launched successfully."),
        ("Agent", "3 findings.\n\nQA-VERDICT: REJECT")]      # an unmatched id is ignored
    ok, why = scoring.subagent_verdict(RunResult(tool_results=results), allowed=["REJECT"])
    assert ok and "REJECT" in why
