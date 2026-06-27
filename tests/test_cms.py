"""Baseline test harness for the cms scripts.

Covers the stable, pure helpers in `common.py` and the validation logic in `check.py`.
Phase 1A (frontmatter-exempt bug fix) will extend this; the known defect is encoded here
as a strict xfail so the fix flips it red and forces removal of the marker.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

import common
import check


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
applies_to: whetstone
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


# --------------------------------------------------------------------------- KNOWN BUG (Phase 1A target)
@pytest.mark.xfail(
    strict=True,
    reason="cms bug: canonical docs/ files (ARCHITECTURE/ROADMAP/LESSONS_LEARNED) are in "
    "ARCHIVE_ALLOWLIST, which is wrongly reused as the frontmatter-exempt set, so they skip "
    "frontmatter validation. Fixed in Phase 1A (FRONTMATTER_EXEMPT split) — when fixed this "
    "xpasses and strict mode forces removal of the marker.",
)
def test_docs_canonical_file_requires_frontmatter(tmp_path):
    f = write(tmp_path / "docs" / "ARCHITECTURE.md", "no frontmatter\n")
    findings = check.run_mechanical_check(f)
    assert any(
        x.level == "error" and "missing frontmatter" in x.message for x in findings
    ), "docs/ARCHITECTURE.md without frontmatter should be an error"
