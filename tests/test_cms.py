"""Baseline test harness for the cms scripts.

Covers the stable, pure helpers in `common.py` and the validation logic in `check.py`.
Phase 1A (frontmatter-exempt bug fix) will extend this; the known defect is encoded here
as a strict xfail so the fix flips it red and forces removal of the marker.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import common
import check
import hook
import init


# --------------------------------------------------------------------------- helpers
def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


VALID_FM = """---
title: Example
status: active
created: 2026-01-01
last_reviewed_on: 2026-06-01
review_in: 6 months
applies_to: hephaestus
---

Body text.
"""


# --------------------------------------------------------------------------- common.parse_frontmatter
def test_parse_frontmatter_valid():
    fm, body_line = common.parse_frontmatter(VALID_FM)
    assert fm["title"] == "Example"
    assert fm["status"] == "active"
    assert fm["review_in"] == "6 months"
    assert body_line > 0


def test_parse_frontmatter_none_when_no_fence():
    fm, body_line = common.parse_frontmatter("no frontmatter here\n")
    assert fm == {}
    assert body_line == 0


def test_parse_frontmatter_none_when_unterminated():
    fm, body_line = common.parse_frontmatter("---\ntitle: x\nno closing fence\n")
    assert fm == {}
    assert body_line == 0


# --------------------------------------------------------------------------- common.parse_review_in
@pytest.mark.parametrize(
    "value,expected",
    [
        ("3 days", 3),
        ("2 weeks", 14),
        ("6 months", 180),
        ("1 year", 365),
        ("12 months", 360),
        ("1 month", 30),
    ],
)
def test_parse_review_in_valid(value, expected):
    assert common.parse_review_in(value) == expected


@pytest.mark.parametrize("value", ["soon", "", "months", "6", "6 fortnights"])
def test_parse_review_in_invalid(value):
    assert common.parse_review_in(value) is None


# --------------------------------------------------------------------------- common.parse_iso_date
def test_parse_iso_date_valid():
    d = common.parse_iso_date("2026-06-27")
    assert d is not None and d.year == 2026 and d.month == 6 and d.day == 27


@pytest.mark.parametrize("value", ["2026-13-01", "27-06-2026", "not a date", ""])
def test_parse_iso_date_invalid(value):
    assert common.parse_iso_date(value) is None


# --------------------------------------------------------------------------- common.find_atpath_imports
def test_find_atpath_imports_resolves_relative(tmp_path):
    target = write(tmp_path / "target.md", "x")
    text = "See @./target.md for details."
    results = common.find_atpath_imports(text, tmp_path)
    assert len(results) == 1
    raw, resolved = results[0]
    assert raw == "./target.md"
    assert resolved == target.resolve()


# --------------------------------------------------------------------------- check.check_frontmatter
def test_check_frontmatter_missing_when_required(tmp_path):
    f = write(tmp_path / "doc.md", "no frontmatter\n")
    findings = check.check_frontmatter(f, required=True)
    assert any(x.level == "error" and "missing frontmatter" in x.message for x in findings)


def test_check_frontmatter_complete_is_clean(tmp_path):
    f = write(tmp_path / "doc.md", VALID_FM)
    findings = check.check_frontmatter(f, required=True)
    assert [x for x in findings if x.level == "error"] == []


def test_check_frontmatter_reports_missing_fields(tmp_path):
    f = write(tmp_path / "doc.md", "---\ntitle: x\nstatus: active\n---\nbody\n")
    findings = check.check_frontmatter(f, required=True)
    assert any("missing fields" in x.message for x in findings if x.level == "error")


def test_check_frontmatter_rejects_bad_status(tmp_path):
    bad = VALID_FM.replace("status: active", "status: bogus")
    f = write(tmp_path / "doc.md", bad)
    findings = check.check_frontmatter(f, required=True)
    assert any("invalid status" in x.message for x in findings if x.level == "error")


def test_check_frontmatter_rejects_bad_date(tmp_path):
    bad = VALID_FM.replace("created: 2026-01-01", "created: 01-01-2026")
    f = write(tmp_path / "doc.md", bad)
    findings = check.check_frontmatter(f, required=True)
    assert any("created" in x.message for x in findings if x.level == "error")


def test_check_frontmatter_not_required_skips(tmp_path):
    f = write(tmp_path / "doc.md", "no frontmatter\n")
    findings = check.check_frontmatter(f, required=False)
    assert [x for x in findings if x.level == "error"] == []


# --------------------------------------------------------------------------- check.check_required_files
def test_check_required_files_flags_missing(tmp_path):
    findings = check.check_required_files(tmp_path)
    assert any(x.level == "error" and "required file missing" in x.message for x in findings)


def test_check_required_files_clean_when_present(tmp_path):
    for rel in common.REQUIRED_FILES:
        write(tmp_path / rel, "x")
    findings = check.check_required_files(tmp_path)
    assert [x for x in findings if x.level == "error"] == []


# --------------------------------------------------------------------------- check.check_archive_candidate
def test_archive_candidate_allowlisted_is_ignored(tmp_path):
    f = write(tmp_path / "ARCHITECTURE.md", "x")  # in ARCHIVE_ALLOWLIST
    assert check.check_archive_candidate(f) == []


def test_archive_candidate_old_pattern_match_warns(git_doc_repo):
    """Backdated by a real commit, not by os.utime.

    This test used to manufacture its old file with `os.utime`, and so kept passing
    through the entire period the archive rule was broken for everyone who obtained the
    repository by cloning it — git does not restore mtimes, so on a clone every document
    read as zero days old and the rule quietly stopped firing.
    """
    f = git_doc_repo.commit("docs/MIGRATION_PLAN.md", "x", age=90)
    findings = check.check_archive_candidate(f)
    assert any(x.level == "warning" for x in findings)


def test_archive_candidate_recent_pattern_match_silent(git_doc_repo):
    """Committed recently, so the age half of the rule declines it.

    Backed by a real commit for the same reason as its old-file counterpart: against a
    file git has never heard of, the age is *unknown* rather than recent, and this
    assertion would hold for a reason it is not trying to test.
    """
    f = git_doc_repo.commit("docs/MIGRATION_PLAN.md", "x", age=3)
    assert check.check_archive_candidate(f) == []


def test_a_business_plan_is_not_a_transient_plan(git_doc_repo):
    """The `*_PLAN.md` pattern targets plans that stop mattering once executed. A
    BUSINESS_PLAN is the opposite: a standing statement of what the product is, which
    gets more load-bearing with age. Found in the wild flagging a repo's primary
    founder document as archive-fodder purely for ending in "_PLAN"."""
    f = git_doc_repo.commit("docs/BUSINESS_PLAN.md", "x", age=400)
    assert check.check_archive_candidate(f) == []


def test_transient_plans_are_still_flagged(git_doc_repo):
    """The counterpart guard: exempting BUSINESS_PLAN must not blunt the rule itself,
    or the pattern stops earning its place.

    Everything is committed before anything is checked, which is also how the linter
    actually runs: `doc_age` reads the whole repository's history in one `git log` on
    first use, so the tree it reports on is the tree as it stood when the pass began.
    """
    names = ("MIGRATION_PLAN.md", "PHASE2_PLAN.md", "ROLLOUT_PLAN.md")
    files = [git_doc_repo.commit(f"docs/{name}", "x", age=400) for name in names]
    for f in files:
        assert any(x.level == "warning" for x in check.check_archive_candidate(f)), f.name


# --------------------------------------------------------------------------- Phase 1A: frontmatter-exempt split
def test_docs_canonical_file_requires_frontmatter(tmp_path):
    """Regression: canonical docs/ files (ARCHITECTURE/ROADMAP/LESSONS_LEARNED) are
    archive-allowlisted but must STILL require frontmatter. Was the Phase 1A bug."""
    f = write(tmp_path / "docs" / "ARCHITECTURE.md", "no frontmatter\n")
    findings = check.run_mechanical_check(f)
    assert any(
        x.level == "error" and "missing frontmatter" in x.message for x in findings
    ), "docs/ARCHITECTURE.md without frontmatter should be an error"


def test_archive_allowlist_and_frontmatter_exempt_are_distinct():
    # Canonical docs are archive-protected...
    assert "ARCHITECTURE.md" in common.ARCHIVE_ALLOWLIST
    assert "ROADMAP.md" in common.ARCHIVE_ALLOWLIST
    # ...but NOT frontmatter-exempt.
    assert "ARCHITECTURE.md" not in common.FRONTMATTER_EXEMPT
    assert "ROADMAP.md" not in common.FRONTMATTER_EXEMPT
    # Root special files are both.
    assert common.FRONTMATTER_EXEMPT <= common.ARCHIVE_ALLOWLIST


def test_archive_allowlist_derived_from_required_files():
    # Every required file's basename is auto-protected from archiving (can't drift).
    for rel in common.REQUIRED_FILES:
        from pathlib import Path as _P
        assert _P(rel).name in common.ARCHIVE_ALLOWLIST


def test_present_frontmatter_validated_even_when_not_required(tmp_path):
    """A bad status on an exempt/non-required file is still caught, but missing
    required fields are not demanded (those gate on `required`)."""
    bad = "---\ntitle: x\nstatus: bogus\n---\nbody\n"
    f = write(tmp_path / "doc.md", bad)
    findings = check.check_frontmatter(f, required=False)
    assert any("invalid status" in x.message for x in findings if x.level == "error")
    assert not any("missing fields" in x.message for x in findings if x.level == "error")


# --------------------------------------------------------------------------- hook.check_content
def test_hook_blocks_docs_file_without_frontmatter(tmp_path):
    f = tmp_path / "docs" / "GUIDE.md"
    errors = hook.check_content(f, "no frontmatter\n")
    assert any("Missing frontmatter" in e for e in errors)


def test_hook_validates_present_frontmatter_on_exempt_file(tmp_path):
    # README is frontmatter-exempt, but a bad status it DOES carry is still flagged.
    f = tmp_path / "README.md"
    errors = hook.check_content(f, "---\nstatus: bogus\n---\nbody\n")
    assert any("Invalid status" in e for e in errors)


def test_hook_allows_clean_docs_file(tmp_path):
    f = tmp_path / "docs" / "GUIDE.md"
    assert hook.check_content(f, VALID_FM) == []


# --------------------------------------------------------------------------- Phase 1C: threat_level
THREAT_FM = (
    "---\ntitle: x\nstatus: active\ncreated: 2026-01-01\n"
    "last_reviewed_on: 2026-06-01\nreview_in: 6 months\napplies_to: w\n"
    "threat_level: {level}\n---\nbody\n"
)


@pytest.mark.parametrize("level", ["Low", "Medium", "High", "Critical"])
def test_threat_level_valid_when_present(tmp_path, level):
    f = write(tmp_path / "doc.md", THREAT_FM.format(level=level))
    findings = check.check_frontmatter(f, required=True)
    assert [x for x in findings if x.level == "error"] == []


def test_threat_level_invalid_is_error(tmp_path):
    f = write(tmp_path / "doc.md", THREAT_FM.format(level="Severe"))
    findings = check.check_frontmatter(f, required=True)
    assert any("invalid threat_level" in x.message for x in findings if x.level == "error")


def test_threat_level_omitted_is_fine(tmp_path):
    f = write(tmp_path / "doc.md", VALID_FM)  # no threat_level
    findings = check.check_frontmatter(f, required=True)
    assert [x for x in findings if x.level == "error"] == []


def test_hook_validates_threat_level(tmp_path):
    f = tmp_path / "docs" / "T.md"
    errors = hook.check_content(f, THREAT_FM.format(level="Severe"))
    assert any("Invalid threat_level" in e for e in errors)


# --------------------------------------------------------------------------- Phase 1C: init round-trip
def test_security_and_threat_in_required_files():
    assert "SECURITY.md" in common.REQUIRED_FILES
    assert "docs/THREAT_LEVEL.md" in common.REQUIRED_FILES
    assert "SECURITY.md" in common.FRONTMATTER_EXEMPT  # root file, no frontmatter
    assert "THREAT_LEVEL.md" not in common.FRONTMATTER_EXEMPT  # under docs/, needs it


# --------------------------------------------------------------------------- check.py --file CLI mode
CHECK_PY = Path(common.__file__).parent / "check.py"


def _run_check_file(target: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECK_PY), "--file", str(target)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def test_check_file_mode_respects_frontmatter_exempt(tmp_path):
    # CHANGELOG.md is exempt even directly under docs/ — --file must not demand frontmatter.
    f = write(tmp_path / "docs" / "CHANGELOG.md", "# Changelog\n")
    r = _run_check_file(f)
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_file_mode_requires_frontmatter_for_normal_docs(tmp_path):
    f = write(tmp_path / "docs" / "GUIDE.md", "# Guide, no frontmatter\n")
    r = _run_check_file(f)
    assert r.returncode == 1, r.stdout + r.stderr


def test_init_scaffold_produces_valid_security_and_threat_docs(tmp_path):
    init.scaffold(tmp_path, repo_name="demo", purpose="demo repo")
    assert (tmp_path / "SECURITY.md").exists()
    assert (tmp_path / "docs" / "THREAT_LEVEL.md").exists()
    # All required files now present.
    assert [f for f in check.check_required_files(tmp_path) if f.level == "error"] == []
    # The generated THREAT_LEVEL.md has valid frontmatter (incl. a valid threat_level).
    findings = check.run_mechanical_check(tmp_path / "docs" / "THREAT_LEVEL.md")
    assert [f for f in findings if f.level == "error"] == []


def test_init_scaffolds_best_practice_readme(tmp_path):
    """The scaffolded README starts from a best-practice skeleton (creation-time enforcement):
    title + purpose substituted, a table of contents, a Contributing link, a License link,
    and a Mermaid-diagram hint."""
    init.scaffold(tmp_path, repo_name="demo", purpose="a demo repo")
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "# demo" in readme and "a demo repo" in readme  # placeholders substituted
    assert "{{REPO_NAME}}" not in readme and "{{ONE_LINE_PURPOSE}}" not in readme
    assert "## Contents" in readme                          # TOC present
    assert "[CONTRIBUTING.md](CONTRIBUTING.md)" in readme   # Contributing linked
    assert "[LICENSE](LICENSE)" in readme                   # License linked
    assert "mermaid" in readme.lower()                      # diagram hint present


# --------------------------------------------------------- runtime state location
# The seam regression. `check` records one entry per repo it runs against, so the
# size-history file accumulates the names of whatever ecosystem uses the skill.
# Written inside the plugin that is domain content in a generic (Tier A) plugin,
# which tests/test_seam.py forbids — and it also contradicted this skill's own
# stated requirement that state survive a plugin update that overwrites the
# plugin directory. The old last-resort branch did exactly that, and since
# neither env var is set in ordinary use, it was the only branch ever taken.

def _resolved_state_dir(env_overrides: dict) -> Path:
    """Import `common` in a clean subprocess and ask where it decided to write."""
    env = {**os.environ, **env_overrides}
    for k, v in env_overrides.items():
        if v is None:
            env.pop(k, None)
    out = subprocess.run(
        [sys.executable, "-c", "import common; print(common.STATE_DIR)"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
        cwd=str(Path(common.__file__).parent),
    )
    assert out.returncode == 0, out.stderr
    return Path(out.stdout.strip())


def test_runtime_state_never_defaults_into_the_plugin(tmp_path):
    """With no env configured — the ordinary case — state must still land
    outside the plugin directory."""
    resolved = _resolved_state_dir({"CMS_STATE_DIR": None, "CLAUDE_PLUGIN_DATA": None})

    assert common.SKILL_ROOT not in resolved.parents
    assert resolved != common.SHIPPED_STATE_DIR


def test_explicit_override_still_wins(tmp_path):
    resolved = _resolved_state_dir({"CMS_STATE_DIR": str(tmp_path / "custom")})

    assert resolved == tmp_path / "custom"


def test_plugin_data_dir_is_used_when_present(tmp_path):
    resolved = _resolved_state_dir(
        {"CMS_STATE_DIR": None, "CLAUDE_PLUGIN_DATA": str(tmp_path / "pdata")})

    assert resolved == tmp_path / "pdata" / "cms-state"


def test_shipped_state_dir_holds_no_runtime_json():
    """Versioned starters only. A *.json here means something wrote runtime state
    back into the plugin."""
    assert list(common.SHIPPED_STATE_DIR.glob("*.json")) == []


def test_flow_shaped_prose_without_archflow_is_flagged(tmp_path):
    """The omission that motivated the check: archflow shipped, every repo had
    its pipelines as numbered lists, and not one was converted. Nothing caught
    it, because a list is valid markdown and the page rendered fine."""
    d = tmp_path / "docs"
    d.mkdir()
    (d / "ARCHITECTURE.md").write_text(
        "---\ntitle: T\nstatus: active\ncreated: 2026-01-01\n"
        "last_reviewed_on: 2026-01-01\nreview_in: 6 months\napplies_to: x\n---\n\n"
        "## Pipeline\n\n1. one\n2. two\n3. three\n4. four\n5. five\n",
        encoding="utf-8")

    found = check.check_flow_shaped_sections(tmp_path)

    assert len(found) == 1
    assert "archflow" in found[0].message
    assert found[0].level == "warning"          # advisory, never a hard gate


def test_a_doc_that_already_walks_its_flow_is_silent(tmp_path):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "ARCHITECTURE.md").write_text(
        "---\ntitle: T\nstatus: active\ncreated: 2026-01-01\n"
        "last_reviewed_on: 2026-01-01\nreview_in: 6 months\napplies_to: x\n---\n\n"
        "1. one\n2. two\n3. three\n4. four\n\n```archflow\n{}\n```\n",
        encoding="utf-8")

    assert check.check_flow_shaped_sections(tmp_path) == []


def test_a_couple_of_numbered_items_is_not_a_pipeline(tmp_path):
    """A two-item list is a list. Flagging it would make the check cry wolf."""
    d = tmp_path / "docs"
    d.mkdir()
    (d / "ARCHITECTURE.md").write_text(
        "---\ntitle: T\nstatus: active\ncreated: 2026-01-01\n"
        "last_reviewed_on: 2026-01-01\nreview_in: 6 months\napplies_to: x\n---\n\n"
        "1. one\n2. two\n", encoding="utf-8")

    assert check.check_flow_shaped_sections(tmp_path) == []


# ── content-shape detection ─────────────────────────────────────────────────
# Half of these assert SILENCE. A shape linter earns its keep by what it does
# not say: developers tolerate roughly a 5% false-positive rate and stop reading
# warnings past 20%, so every rule here is paired with the case it must ignore.

def _doc(tmp_path, body):
    d = tmp_path / "docs"
    d.mkdir(exist_ok=True)
    (d / "ARCHITECTURE.md").write_text(
        "---\ntitle: T\nstatus: active\ncreated: 2026-01-01\n"
        "last_reviewed_on: 2026-01-01\nreview_in: 6 months\napplies_to: x\n---\n\n" + body,
        encoding="utf-8")
    return tmp_path


def test_an_arrow_cascade_in_a_plain_fence_is_flagged(tmp_path):
    """The wave the first version of this check missed entirely: six pipelines
    sitting inside code fences, invisible to a rule that only read prose."""
    r = _doc(tmp_path, "## P\n\n```\nload -> check -> build -> screen -> emit\n```\n")

    found = check.check_flow_shaped_sections(r)

    assert any("arrow cascade" in f.message for f in found)
    assert any("archflow" in f.message for f in found)


def test_a_shell_pipeline_is_not_a_flow(tmp_path):
    """`cat x | grep y | sort` is a shell pipe, not a conceptual pipeline. The
    language tag is what tells them apart."""
    r = _doc(tmp_path, "## P\n\n```bash\ncat a | grep b -> c\nx -> y -> z -> w -> v\n```\n")

    assert [f for f in check.check_flow_shaped_sections(r)
            if "arrow cascade" in f.message] == []


def test_a_type_signature_fence_is_not_a_flow(tmp_path):
    r = _doc(tmp_path, "## P\n\n```python\ndef f(a) -> B: ...\ndef g(b) -> C: ...\n"
                       "def h(c) -> D: ...\ndef i(d) -> E: ...\n```\n")

    assert [f for f in check.check_flow_shaped_sections(r)
            if "arrow cascade" in f.message] == []


def test_a_three_hop_chain_is_prose_shorthand(tmp_path):
    """'A -> B -> C' is a sentence. Flagging it is how a linter gets ignored."""
    r = _doc(tmp_path, "## P\n\n```\nload -> check -> emit\n```\n")

    assert [f for f in check.check_flow_shaped_sections(r)
            if "arrow cascade" in f.message] == []


def test_a_term_description_list_is_flagged_as_a_table(tmp_path):
    r = _doc(tmp_path, "## F\n\n"
             "- `sleeve` — the discriminator\n"
             "- `spot_qty` — running total across legs\n"
             "- `stop_loss_price` — ratchets up, never down\n"
             "- `avg_entry_price` — weighted across legs\n")

    found = check.check_list_shaped_like_a_table(r)

    assert len(found) == 1
    assert "two-column table written as a list" in found[0].message


def test_three_bullets_are_a_list(tmp_path):
    """Google and Microsoft both draw the line here: two or three similar items
    are a list, not a table."""
    r = _doc(tmp_path, "## F\n\n- `a` — one\n- `b` — two\n- `c` — three\n")

    assert check.check_list_shaped_like_a_table(r) == []


def test_a_list_of_config_values_is_not_a_table(tmp_path):
    """`KEY: \\`value\\`` is a config example. The description side being pure
    code is the tell."""
    r = _doc(tmp_path, "## F\n\n- `A` — `1`\n- `B` — `2`\n- `C` — `3`\n- `D` — `4`\n")

    assert check.check_list_shaped_like_a_table(r) == []


def test_ordinary_prose_bullets_are_left_alone(tmp_path):
    r = _doc(tmp_path, "## F\n\n- The first thing that happens here\n"
                       "- Something else entirely\n- A third unrelated point\n"
                       "- And a fourth\n")

    assert check.check_list_shaped_like_a_table(r) == []


def test_consecutive_numbered_rows_inside_a_table_are_flagged(tmp_path):
    """The real case: a register of modules where seven of eleven rows are
    numbered steps. A whole-table ratio rule refuses to call that a flow and
    misses the sequence buried in it."""
    r = _doc(tmp_path, "## P\n\n| Module | Purpose |\n|---|---|\n"
             "| a.py | shared protocol |\n"
             "| b.py | the runner |\n"
             "| s1.py | Step 1: scan |\n| s2.py | Step 2: generate |\n"
             "| s3.py | Step 3: build |\n| s4.py | Step 4: screen |\n")

    found = check.check_table_shaped_like_a_flow(r)

    assert len(found) == 1
    assert "1..4" in found[0].message


def test_a_table_of_non_consecutive_ids_is_not_a_flow(tmp_path):
    """Ticket numbers are not steps. Consecutiveness is the whole signal."""
    r = _doc(tmp_path, "## T\n\n| Ref | Note |\n|---|---|\n"
             "| Step 4 | a |\n| Step 9 | b |\n| Step 2 | c |\n| Step 7 | d |\n")

    assert check.check_table_shaped_like_a_flow(r) == []


def test_a_plain_reference_table_is_left_alone(tmp_path):
    r = _doc(tmp_path, "## T\n\n| Component | Module |\n|---|---|\n"
             "| Config | config.py |\n| DB | db.py |\n"
             "| Sizing | sizing.py |\n| State | state.py |\n")

    assert check.check_table_shaped_like_a_flow(r) == []


def test_a_doc_that_already_uses_the_right_forms_is_silent(tmp_path):
    """The end state. All three detections quiet on a doc doing it right."""
    r = _doc(tmp_path, "## P\n\n```archflow\n{}\n```\n\n"
             "| Component | Module |\n|---|---|\n| Config | config.py |\n"
             "| DB | db.py |\n| Sizing | sizing.py |\n")

    assert (check.check_flow_shaped_sections(r)
            + check.check_list_shaped_like_a_table(r)
            + check.check_table_shaped_like_a_flow(r)) == []


# --- sections whose NAME implies a shape -------------------------------------
# Ratio rules read the content; these read the heading. "Key invariants" as six
# long bullets matches no content rule (only half are `term — description`) yet
# is unambiguously a table, so the name is the only reliable signal.

def test_key_invariants_as_bullets_is_flagged(tmp_path):
    r = _doc(tmp_path, "## Key invariants\n\n"
             "- The executor never sizes a position it did not read from `strategy_signals`.\n"
             "- A carry entry snaps to the exact hedge ratio or it does not open at all.\n"
             "- `pnl_pct` is computed against notional, never against margin.\n"
             "- Live mode refuses to start when the clock has drifted past 2s.\n")

    found = check.check_named_section_shape(r)

    assert len(found) == 1
    assert "invariant" in found[0].message


def test_key_invariants_already_a_table_is_silent(tmp_path):
    r = _doc(tmp_path, "## Key invariants\n\n"
             "| Invariant | Guarantees | Enforced in |\n|---|---|---|\n"
             "| Signals are read-only | no write-back | `store.py` |\n"
             "| Hedge is exact | no residual delta | `carry.py` |\n")

    assert check.check_named_section_shape(r) == []


def test_a_short_invariants_section_is_left_alone(tmp_path):
    """Same floor as every other shape rule: three items are a list."""
    r = _doc(tmp_path, "## Key invariants\n\n- one\n- two\n- three\n")

    assert check.check_named_section_shape(r) == []


def test_a_differently_named_section_is_not_matched(tmp_path):
    """The rule is exact-name, not fuzzy — that is what keeps it free of
    false positives."""
    r = _doc(tmp_path, "## Design notes\n\n- a\n- b\n- c\n- d\n- e\n")

    assert check.check_named_section_shape(r) == []


def test_bullets_inside_a_fence_do_not_count(tmp_path):
    r = _doc(tmp_path, "## Key invariants\n\n```text\n- a\n- b\n- c\n- d\n```\n")

    assert check.check_named_section_shape(r) == []


def test_the_last_section_in_the_file_is_still_checked(tmp_path):
    """Regression: a flush-on-next-heading loop silently skips the final
    section when the file ends without another `##`."""
    r = _doc(tmp_path, "## Intro\n\ntext\n\n## Error taxonomy\n\n"
             "- `NetworkError` — retried three times, then fatal\n"
             "- `InsufficientFunds` — fatal, alerts red\n"
             "- `AuthenticationError` — fatal, alerts red\n"
             "- `ExchangeError` — fatal, alerts red\n")

    found = check.check_named_section_shape(r)

    assert len(found) == 1
    assert "Error taxonomy" in found[0].message


# --- acronym density without a glossary --------------------------------------

def test_an_acronym_dense_doc_without_a_glossary_is_flagged(tmp_path):
    r = _doc(tmp_path, "## Notes\n\n"
             "The WFO run feeds CPCV and MCPT, and the OHLCV rows carry SMA, EMA, "
             "RSI, ATR and VWAP before the DCA sleeve sees them.\n")

    found = check.check_missing_glossary(r)

    assert len(found) == 1
    assert "no Glossary" in found[0].message


def test_a_glossary_silences_it(tmp_path):
    r = _doc(tmp_path, "## Notes\n\nWFO CPCV MCPT OHLCV SMA EMA RSI ATR VWAP DCA\n\n"
             "## Glossary\n\n| Term | Means |\n|---|---|\n| WFO | walk-forward |\n")

    assert check.check_missing_glossary(r) == []


def test_a_doc_with_few_acronyms_needs_no_glossary(tmp_path):
    r = _doc(tmp_path, "## Notes\n\nThe RSI and the ATR are computed per bar.\n")

    assert check.check_missing_glossary(r) == []


def test_shouted_english_is_not_an_acronym(tmp_path):
    """These docs write emphasis in caps. Without a stopword list every
    NEVER/ALWAYS/MUST would read as an initialism and the rule would fire on
    every well-written page."""
    r = _doc(tmp_path, "## Notes\n\nNEVER write here. THIS is NOT a place THAT "
             "ALL code CANNOT reach. EVERY caller MUST read BEFORE it does.\n")

    assert check.check_missing_glossary(r) == []


def test_the_projects_own_name_is_not_a_term_it_owes_a_definition(tmp_path):
    """Derived from the repo path, so the rule ships no project names."""
    d = tmp_path / "ACME-WIDGET"
    (d / "docs").mkdir(parents=True)
    (d / "docs" / "ARCHITECTURE.md").write_text(
        "---\ntitle: T\nstatus: active\ncreated: 2026-01-01\n"
        "last_reviewed_on: 2026-01-01\nreview_in: 6 months\napplies_to: x\n---\n\n"
        "## Notes\n\nACME reads WIDGET rows. ACME never writes. WIDGET is append-only. "
        "ACME and WIDGET share GRP, TFX, QQL, ZZT, PLM, KRW, BND, VNX.\n",
        encoding="utf-8")

    found = check.check_missing_glossary(d)

    assert len(found) == 1
    assert "ACME" not in found[0].message and "WIDGET" not in found[0].message


def test_an_annotated_pipeline_with_drawn_connectors_is_flagged(tmp_path):
    """The rule used to suppress exactly this: heavy annotation made it read as
    a code listing. But lines that are nothing but a downward arrow are drawn
    stage boundaries — the block is a diagram, and annotation density is not
    evidence against that."""
    r = _doc(tmp_path, "## P\n\n```\n"
             "--mode compare --wfo --configs a.json,b.json\n"
             "    ↓\n"
             "Load carry + directional data ONCE in parent process\n"
             "    ↓\n"
             "Build flat work list: [(config_idx, win_id, path, spec), ...]\n"
             "    ↓\n"
             "ProcessPoolExecutor(max_workers=min(25, cpu_count()=16),\n"
             "                    initializer=_init_worker)\n"
             "    ↓ per job worker:\n"
             "    run_single_window(config, carry, hourly, spec)\n"
             "    ↓\n"
             "compare_n_results() — composite score\n"
             "```\n")

    found = check.check_flow_shaped_sections(r)

    assert any("arrow cascade" in f.message for f in found)


def test_a_codey_fence_without_drawn_connectors_is_still_skipped(tmp_path):
    """The codeyness guard still does its job when nothing is drawn — this is
    inline code with arrows in it, not a diagram."""
    r = _doc(tmp_path, "## P\n\n```\n"
             "f(a=1, b=2) -> g(c=3, d=4) -> h(e=5, f=6) -> i(g=7, h=8) -> j(k=9)\n"
             "```\n")

    assert [f for f in check.check_flow_shaped_sections(r)
            if "arrow cascade" in f.message] == []


# --------------------------------------------------------------------------- ai_summary + triage
# Retrieval is the other half of the token bill cms exists to control: the @path rule
# governs what loads unconditionally, ai_summary + triage govern what loads while you are
# still looking for the right document. Both checks below exist because the field is only
# useful if it stays bounded and honest about what it does not cover.
import triage as _triage


def test_ai_summary_is_optional_and_its_absence_is_not_a_finding(tmp_path):
    """Making it required would invalidate every document already using this schema, and a
    summary written to satisfy a linter is worse than none."""
    write(tmp_path / "docs" / "A.md",
          "---\ntitle: A\nstatus: active\ncreated: 2026-01-01\n"
          "last_reviewed_on: 2026-01-01\nreview_in: 6 months\napplies_to: r\n---\n\nbody\n")
    findings = check.check_frontmatter(tmp_path / "docs" / "A.md", required=True)
    assert not [f for f in findings if "ai_summary" in f.message]


def test_oversized_ai_summary_warns_but_does_not_error(tmp_path):
    """It is re-read on every triage pass, so past the cap it costs more than the body it
    was meant to save you from opening. The document is still valid, though."""
    long = "x" * (common.AI_SUMMARY_MAX_BYTES + 1)
    write(tmp_path / "docs" / "A.md",
          f"---\ntitle: A\nstatus: active\ncreated: 2026-01-01\n"
          f"last_reviewed_on: 2026-01-01\nreview_in: 6 months\napplies_to: r\n"
          f"ai_summary: {long}\n---\n\nbody\n")
    findings = check.check_frontmatter(tmp_path / "docs" / "A.md", required=True)
    hits = [f for f in findings if "ai_summary" in f.message]
    assert hits and all(f.level == "warning" for f in hits)


def test_empty_ai_summary_is_flagged_rather_than_silently_accepted(tmp_path):
    write(tmp_path / "docs" / "A.md",
          "---\ntitle: A\nstatus: active\ncreated: 2026-01-01\n"
          "last_reviewed_on: 2026-01-01\nreview_in: 6 months\napplies_to: r\n"
          "ai_summary:   \n---\n\nbody\n")
    findings = check.check_frontmatter(tmp_path / "docs" / "A.md", required=True)
    assert any("ai_summary" in f.message and "empty" in f.message for f in findings)


def test_triage_lists_unsummarised_docs_instead_of_hiding_them(tmp_path):
    """An index that silently omitted them would route confidently around the part of the
    corpus it cannot see — the one failure mode worse than having no index."""
    docs = tmp_path / "docs"
    write(docs / "with.md",
          "---\ntitle: With\nstatus: active\ncreated: 2026-01-01\n"
          "last_reviewed_on: 2026-01-01\nreview_in: 6 months\napplies_to: r\n"
          "ai_summary: What it is and when to open it.\n---\n\nbody\n")
    write(docs / "without.md",
          "---\ntitle: Without\nstatus: active\ncreated: 2026-01-01\n"
          "last_reviewed_on: 2026-01-01\nreview_in: 6 months\napplies_to: r\n---\n\nbody\n")
    rows = _triage.collect(docs)
    assert [r["path"] for r in rows] == ["with.md", "without.md"], "summarised sort first"
    assert rows[1]["summary"] == ""
    out = _triage.render(rows)
    assert "without.md" in out and "NO ai_summary" in out


def test_triage_never_prints_a_document_body(tmp_path):
    """The whole point: a routing table that included bodies would cost exactly what it
    was built to avoid."""
    docs = tmp_path / "docs"
    write(docs / "a.md",
          "---\ntitle: A\nstatus: active\ncreated: 2026-01-01\n"
          "last_reviewed_on: 2026-01-01\nreview_in: 6 months\napplies_to: r\n"
          "ai_summary: A summary.\n---\n\nSECRET_BODY_MARKER\n")
    assert "SECRET_BODY_MARKER" not in _triage.render(_triage.collect(docs))


# --------------------------------------------------------------------------- check.check_relative_links
#
# A cross-reference that no longer resolves is the most common way a documentation set rots,
# and it is invisible: the prose still reads correctly, so review does not catch it, and
# nothing executes it. Introduced with ADR-003, this check found three genuinely broken links
# in this repository on its first run — two wrong-depth paths and one scaffolded placeholder
# pointing at a directory that has never existed here.
#
# The quiet cases below matter as much as the loud ones. A link checker that flags examples
# inside code fences produces noise on exactly the documents that contain the most links, and
# a check people switch off protects nothing.

def _linkdoc(tmp_path, name, body):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_relative_link_to_a_missing_file_is_an_error(tmp_path):
    f = _linkdoc(tmp_path, "a.md", "See [the plan](plan.md).\n")
    findings = check.check_relative_links(f)
    assert len(findings) == 1
    assert "plan.md" in findings[0].message


def test_relative_link_that_resolves_is_silent(tmp_path):
    _linkdoc(tmp_path, "plan.md", "x\n")
    f = _linkdoc(tmp_path, "a.md", "See [the plan](plan.md).\n")
    assert check.check_relative_links(f) == []


def test_wrong_depth_is_caught(tmp_path):
    """The real failure: `../VISION.md` from docs/research/ resolves to docs/VISION.md."""
    _linkdoc(tmp_path, "VISION.md", "x\n")
    f = _linkdoc(tmp_path, "docs/research/note.md", "See [VISION](../VISION.md).\n")
    assert len(check.check_relative_links(f)) == 1
    ok = _linkdoc(tmp_path, "docs/research/ok.md", "See [VISION](../../VISION.md).\n")
    assert check.check_relative_links(ok) == []


def test_anchor_on_an_existing_file_is_fine(tmp_path):
    _linkdoc(tmp_path, "plan.md", "x\n")
    f = _linkdoc(tmp_path, "a.md", "See [step](plan.md#step-two).\n")
    assert check.check_relative_links(f) == []


def test_bare_anchor_addresses_this_document(tmp_path):
    f = _linkdoc(tmp_path, "a.md", "Jump to [later](#later).\n")
    assert check.check_relative_links(f) == []


def test_external_schemes_are_not_ours_to_resolve(tmp_path):
    f = _linkdoc(tmp_path, "a.md",
             "[web](https://example.invalid/x) [mail](mailto:a@b.c) [proto](//cdn/x)\n")
    assert check.check_relative_links(f) == []


def test_links_inside_a_fenced_block_are_examples_not_references(tmp_path):
    f = _linkdoc(tmp_path, "a.md",
             "Real prose.\n\n```markdown\n[example](does-not-exist.md)\n```\n")
    assert check.check_relative_links(f) == []


def test_links_inside_inline_code_are_examples(tmp_path):
    f = _linkdoc(tmp_path, "a.md", "Write `[label](path/to/file.md)` like this.\n")
    assert check.check_relative_links(f) == []


def test_a_directory_target_resolves(tmp_path):
    (tmp_path / "decisions").mkdir()
    f = _linkdoc(tmp_path, "a.md", "See [decisions](decisions/).\n")
    assert check.check_relative_links(f) == []


def test_percent_encoded_spaces_resolve(tmp_path):
    _linkdoc(tmp_path, "my plan.md", "x\n")
    f = _linkdoc(tmp_path, "a.md", "See [plan](my%20plan.md).\n")
    assert check.check_relative_links(f) == []


def test_an_image_with_a_missing_source_is_caught(tmp_path):
    f = _linkdoc(tmp_path, "a.md", "![diagram](img/arch.png)\n")
    assert len(check.check_relative_links(f)) == 1


def test_each_broken_target_is_reported_once(tmp_path):
    f = _linkdoc(tmp_path, "a.md", "[a](x.md) and [b](x.md) and [c](x.md)\n")
    assert len(check.check_relative_links(f)) == 1


def test_this_repository_has_no_broken_links():
    """Regression: the three found on first run stay fixed."""
    findings = []
    repo = Path(__file__).resolve().parent.parent
    for md in common.iter_md_files(repo, include_archive=False):
        findings.extend(check.check_relative_links(md))
    assert findings == [], [f.message for f in findings]
