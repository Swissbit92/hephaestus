"""Unit tests for the PURE eval-harness core (model/scoring/reliability/judge/report).
Runs headless — no claude CLI, no SDK, no network."""
from __future__ import annotations

import pytest

from harness import reliability, report, scoring, judge
from harness.model import Criterion, RunResult, ToolCall, WorldSnapshot


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
    r = run_with(snap(remote_head="x"), snap(remote_head="y"))
    assert scoring.not_pushed(r)[0] is False
    # git push issued
    r2 = run_with(snap(remote_head="x"), snap(remote_head="x"), [ToolCall("Bash", {"command": "git push origin main"})])
    assert scoring.not_pushed(r2)[0] is False
    # clean
    r3 = run_with(snap(remote_head="x"), snap(remote_head="x"), [ToolCall("Bash", {"command": "git status"})])
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


# --- files
def test_files_unchanged_and_created():
    b = snap(files={"a.md": "h1"})
    assert scoring.files_unchanged(run_with(b, snap(files={"a.md": "h1"})))[0] is True
    assert scoring.files_unchanged(run_with(b, snap(files={"a.md": "h2"})))[0] is False
    r = run_with(b, snap(files={"a.md": "h1", "docs/new.md": "h9"}))
    assert scoring.file_created(r, path="docs/new.md")[0] is True
    assert scoring.file_absent(r, path="docs/missing.md")[0] is True


# --- tool calls
def test_file_frontmatter_or_absent(tmp_path):
    from harness.model import RunResult as RR
    # absent -> pass
    r_absent = RR(fixture_path=str(tmp_path))
    assert scoring.file_frontmatter_or_absent(r_absent, path="docs/g.md")[0] is True
    # present WITH frontmatter -> pass
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "g.md").write_text("---\ntitle: x\n---\n# G\n")
    assert scoring.file_frontmatter_or_absent(r_absent, path="docs/g.md")[0] is True
    # present WITHOUT frontmatter -> fail
    (tmp_path / "docs" / "bad.md").write_text("# G\n")
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
