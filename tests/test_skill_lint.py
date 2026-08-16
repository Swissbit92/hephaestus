"""Tests for the skill-quality linter.

The linter exists to catch the two failure modes that no single diff introduces and no
manifest check can see: a SKILL.md quietly outgrowing its context budget, and two skills
drifting into saying the same thing. Both were present in this repo when the linter was
written — which is why the thresholds are pinned by tests rather than left as constants
someone can relax to make a build green.

The cases below are the ones that make the checks non-trivial:
- an unterminated frontmatter block must be an ERROR, not a silent empty parse;
- a frontmatter name that disagrees with its directory is a routing bug, because the
  runtime discovers skills by directory;
- duplicated *code* is legitimate reuse and must not be reported as duplicated prose;
- "found nothing to lint" must never share an exit code with "everything is fine".
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import skill_lint as sl

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugins" / "crucible" / "scripts" / "skill_lint.py"


def _skill(root: Path, plugin: str, name: str, description: str = "Does a thing. Use when asked.",
           body: str = "Some body prose.\n", frontmatter_extra: str = "") -> Path:
    """Write a minimal but valid SKILL.md into a fake marketplace tree."""
    p = root / "plugins" / plugin / "skills" / name / "SKILL.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    fm = f"---\nname: {name}\ndescription: {description}\n{frontmatter_extra}---\n\n"
    p.write_text(fm + body, encoding="utf-8")
    return p


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)


def _codes(findings) -> set[str]:
    return {f.code for f in findings}


# --------------------------------------------------------------------------- frontmatter
def test_missing_description_is_an_error(tmp_path):
    p = _skill(tmp_path, "p", "alpha")
    p.write_text("---\nname: alpha\n---\n\nbody\n", encoding="utf-8")
    code, findings, _ = sl.run(tmp_path, strict=False)
    assert code == 1
    assert any(f.level == sl.ERROR and "description" in f.message for f in findings)


def test_unterminated_frontmatter_is_an_error_not_a_silent_empty_parse(tmp_path):
    """A missing closing --- makes a naive parser see no keys at all, which would surface
    as 'missing name' and send the author looking in the wrong place."""
    p = _skill(tmp_path, "p", "alpha")
    p.write_text("---\nname: alpha\ndescription: x\n\nbody with no closing fence\n", encoding="utf-8")
    code, findings, _ = sl.run(tmp_path, strict=False)
    assert code == 1
    assert any("not terminated" in f.message for f in findings)


def test_name_must_match_its_directory(tmp_path):
    """The runtime discovers a skill by its directory name; a disagreeing frontmatter name
    means the skill is invoked under one name and documents itself under another."""
    p = _skill(tmp_path, "p", "alpha")
    p.write_text("---\nname: beta\ndescription: x\n---\n\nbody\n", encoding="utf-8")
    code, findings, _ = sl.run(tmp_path, strict=False)
    assert code == 1
    assert any(f.code == "naming" for f in findings)


def test_non_kebab_name_is_an_error(tmp_path):
    p = _skill(tmp_path, "p", "Alpha_Skill")
    code, findings, _ = sl.run(tmp_path, strict=False)
    assert code == 1
    assert any(f.code == "naming" and "kebab" in f.message for f in findings)


def test_unsanctioned_frontmatter_key_is_a_portability_warning(tmp_path):
    """Unknown keys are inert in some runtimes rather than rejected, so the cost is a
    silent behaviour difference — a warning, not an error."""
    _skill(tmp_path, "p", "alpha", frontmatter_extra="colour: blue\n")
    code, findings, _ = sl.run(tmp_path, strict=False)
    assert code == 0, "an unknown key must not fail a non-strict run"
    assert any(f.code == "portability" and "colour" in f.message for f in findings)


def test_sanctioned_keys_do_not_warn(tmp_path):
    _skill(tmp_path, "p", "alpha",
           frontmatter_extra="disable-model-invocation: true\nmetadata:\n  depends_on: [x]\n")
    code, findings, _ = sl.run(tmp_path, strict=False)
    assert "portability" not in _codes(findings)
    assert code == 0


# --------------------------------------------------------------------------- token budget
def test_oversized_skill_is_reported_with_its_estimate(tmp_path):
    _skill(tmp_path, "p", "alpha", body="word " * (sl.TOKEN_WARN * 4))
    _, findings, skills = sl.run(tmp_path, strict=False)
    tok = next(f for f in findings if f.code == "tokens")
    assert f">{sl.TOKEN_WARN}" in tok.message
    assert skills[0]["tokens"] > sl.TOKEN_WARN


def test_a_skill_at_the_threshold_does_not_warn(tmp_path):
    """Pins the boundary: the check is `>`, not `>=`, so a skill sitting exactly on budget
    is not nagged into a pointless edit."""
    _skill(tmp_path, "p", "alpha", body="x")
    _, findings, _ = sl.run(tmp_path, strict=False)
    assert "tokens" not in _codes(findings)


# --------------------------------------------------------------------------- overlap
def test_near_identical_descriptions_are_reported(tmp_path):
    shared = ("Audit a repository for structural decay, dead code and configuration "
              "drift, then report ranked findings. Use when asked to review repo health.")
    _skill(tmp_path, "p", "alpha", description=shared)
    _skill(tmp_path, "p", "beta", description=shared.replace("Audit", "Inspect"))
    code, findings, _ = sl.run(tmp_path, strict=False)
    over = [f for f in findings if f.code == "overlap"]
    assert over and "description overlap" in over[0].message


def test_duplicated_prose_between_two_skills_is_reported(tmp_path):
    passage = ("the gate must refuse to proceed whenever the recorded baseline is red "
               "because a failing baseline is not a licence to merge anything at all ")
    _skill(tmp_path, "p", "alpha", description="Alpha does alpha things. Use when alpha.",
           body=passage * 3)
    _skill(tmp_path, "p", "beta", description="Beta does entirely unrelated beta work.",
           body=passage * 3)
    _, findings, _ = sl.run(tmp_path, strict=False)
    over = [f for f in findings if f.code == "overlap"]
    assert over and "duplicated" in over[0].message


def test_shared_code_blocks_are_not_counted_as_duplicated_prose(tmp_path):
    """Two skills quoting the same command is correct reuse. Counting fenced code would
    bury the prose signal under false positives and train people to ignore the check."""
    code_block = "```bash\n" + "git rev-parse --abbrev-ref HEAD && git status --porcelain\n" * 6 + "```\n"
    _skill(tmp_path, "p", "alpha", description="Alpha does alpha things only.",
           body="Alpha prose that is wholly its own.\n" + code_block)
    _skill(tmp_path, "p", "beta", description="Beta is concerned with different matters.",
           body="Beta prose sharing nothing with the other.\n" + code_block)
    _, findings, _ = sl.run(tmp_path, strict=False)
    assert "overlap" not in _codes(findings)


def test_shingle_helper_ignores_fenced_code():
    """Fences are line-anchored, as CommonMark requires — the closing ``` must start its
    own line, which is what the stripper keys on."""
    assert sl.shingles("```\n" + "alpha beta\n" * 20 + "```\n") == set()


def test_shingle_helper_keeps_prose_around_a_fence():
    body = "prose one two three four five six seven eight nine ten eleven twelve\n```\ncode\n```\n"
    assert sl.shingles(body), "stripping a fence must not discard the prose around it"


# --------------------------------------------------------------------------- exit codes
def test_no_skills_is_exit_2_not_a_pass(tmp_path):
    """'I found nothing to check' must never share an exit code with 'everything is fine'."""
    code, _, _ = sl.run(tmp_path, strict=False)
    assert code == 2


def test_strict_promotes_warnings_to_a_failure(tmp_path):
    _skill(tmp_path, "p", "alpha", body="word " * (sl.TOKEN_WARN * 4))
    assert sl.run(tmp_path, strict=False)[0] == 0
    assert sl.run(tmp_path, strict=True)[0] == 1


def test_clean_tree_exits_zero_even_in_strict_mode(tmp_path):
    _skill(tmp_path, "p", "alpha", description="Alpha handles alpha matters exclusively.")
    _skill(tmp_path, "p", "beta", description="Beta concerns itself with unrelated duties.")
    assert sl.run(tmp_path, strict=True)[0] == 0


# --------------------------------------------------------------------------- CLI
def test_cli_reports_missing_directory_as_could_not_determine():
    p = _run("--repo", "definitely/not/here")
    assert p.returncode == 2
    assert "cannot determine" in p.stderr


def test_cli_json_output_is_parseable_and_carries_findings(tmp_path):
    _skill(tmp_path, "p", "alpha", body="word " * (sl.TOKEN_WARN * 4))
    p = _run("--repo", str(tmp_path), "--json")
    data = json.loads(p.stdout)
    assert data["exit"] == 0
    assert any(f["code"] == "tokens" for f in data["findings"])
    assert "body" not in data["skills"][0], "bodies must not bloat machine-readable output"


def test_cli_says_warnings_are_not_failing_when_they_are_not(tmp_path):
    _skill(tmp_path, "p", "alpha", body="word " * (sl.TOKEN_WARN * 4))
    p = _run("--repo", str(tmp_path))
    assert p.returncode == 0
    assert "do not fail without --strict" in p.stdout


# --------------------------------------------------------------------------- this repo
def test_this_marketplace_passes_its_own_linter_in_strict_mode():
    """The gate CI runs. If this fails, a skill in this repo has drifted — fix the skill,
    not the threshold."""
    p = _run("--repo", str(REPO_ROOT), "--strict")
    assert p.returncode == 0, f"skill_lint --strict failed:\n{p.stdout}\n{p.stderr}"
