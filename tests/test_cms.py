"""Baseline test harness for the cms scripts.

Covers the stable, pure helpers in `common.py` and the validation logic in `check.py`.
Phase 1A (frontmatter-exempt bug fix) will extend this; the known defect is encoded here
as a strict xfail so the fix flips it red and forces removal of the marker.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import common
import check
import hook
import init


# --------------------------------------------------------------------------- helpers
def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
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


def test_archive_candidate_old_pattern_match_warns(tmp_path):
    f = write(tmp_path / "MIGRATION_PLAN.md", "x")
    old = time.time() - 90 * 86400  # 90 days ago
    os.utime(f, (old, old))
    findings = check.check_archive_candidate(f)
    assert any(x.level == "warning" for x in findings)


def test_archive_candidate_recent_pattern_match_silent(tmp_path):
    f = write(tmp_path / "MIGRATION_PLAN.md", "x")  # fresh mtime
    assert check.check_archive_candidate(f) == []


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
        capture_output=True, text=True,
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
