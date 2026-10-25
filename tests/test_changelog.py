"""Tests for scripts/changelog.py: cut, check, archive, archive-lessons, report."""
from __future__ import annotations

from datetime import date

import pytest

import changelog as cl

PRE = "# Changelog\n\nintro line\n\n"
LOG = (
    PRE
    + "## [Unreleased]\n\n### Fixed\n\n- **crucible 1.8.0: a fix.** body\n\n"
    + "## [crucible-v1.7.1] — 2026-10-25\n\n### Fixed\n\n- one\n\n"
    + "## [crucible-v1.7.0] — 2026-10-24\n\n### Added\n\n- two\n\n"
    + "## [crucible-v1.6.1] — 2026-10-01\n\n- three\n\n"
    + "## [0.1.0] — 2026-06-28\n\n### Added\n\n- Initial scaffolding.\n"
)


def test_cut_moves_unreleased_under_a_dated_tag_heading():
    out = cl.cut(LOG, "crucible-v1.8.0", "2026-11-01")
    pre, secs = cl.split_sections(out)
    heads = [h.strip() for h, _ in secs]
    assert heads[:3] == ["## [Unreleased]", "## [crucible-v1.8.0] — 2026-11-01", "## [crucible-v1.7.1] — 2026-10-25"]
    assert secs[0][1].strip() == ""           # a fresh, empty Unreleased
    assert "a fix" in secs[1][1]
    assert pre == PRE


def test_cut_refuses_an_empty_unreleased():
    empty = LOG.replace("### Fixed\n\n- **crucible 1.8.0: a fix.** body\n\n", "", 1)
    with pytest.raises(cl.ChangelogError, match="empty"):
        cl.cut(empty, "crucible-v1.8.0", "2026-11-01")


def test_cut_refuses_a_duplicate_heading_and_a_missing_unreleased():
    with pytest.raises(cl.ChangelogError, match="already has"):
        cl.cut(LOG, "crucible-v1.7.1", "2026-11-01")
    with pytest.raises(cl.ChangelogError, match="no `## \\[Unreleased\\]`"):
        cl.cut(PRE + "## [crucible-v1.7.1] — 2026-10-25\n\n- one\n", "crucible-v1.8.0", "2026-11-01")


def test_cut_then_check_roundtrip_and_cut_is_not_repeatable():
    out = cl.cut(LOG, "crucible-v1.8.0", "2026-11-01")
    assert cl.has_release(out, "crucible-v1.8.0")
    assert not cl.has_release(LOG, "crucible-v1.8.0")
    with pytest.raises(cl.ChangelogError):
        cl.cut(out, "crucible-v1.8.1", "2026-11-02")      # Unreleased is empty again


def test_a_heading_inside_a_code_fence_is_not_a_section():
    text = PRE + "## [Unreleased]\n\n```\n## [fake] — 2026-01-01\n```\n\n- x\n"
    assert [cl._name(h) for h, _ in cl.split_sections(text)[1]] == ["Unreleased"]


def test_archive_keeps_the_newest_n_versions_and_leaves_a_pointer():
    new, moved, n = cl.archive_changelog(LOG, keep=2, on="2026-11-01")
    assert n == 2
    assert "crucible-v1.6.1" in moved and "[0.1.0]" in moved and "crucible-v1.7.1" not in moved
    assert "crucible-v1.7.0" in new and "crucible-v1.6.1" not in new
    assert new.rstrip().endswith(cl.POINTER_CHANGELOG)
    assert "## [Unreleased]" in new                       # Unreleased never archived
    assert cl.archive_changelog(new, keep=2, on="2026-11-01")[2] == 0     # idempotent


def test_archive_pointer_is_added_once():
    once, *_ = cl.archive_changelog(LOG, keep=2, on="2026-11-01")
    again, _, n = cl.archive_changelog(once + "\n## [crucible-v0.0.1] — 2026-01-01\n\n- old\n", keep=2, on="2026-12-01")
    assert n == 1 and again.count(cl.POINTER_CHANGELOG) == 1


LESSONS = (
    "# Lessons\n\nhow to read\n\n"
    "## 2026-10-25 — newest\n\nbody a\n\n"
    "## 2026-10-24 — second\n\nbody b\n\n"
    "## 2026-08-22 — middle\n\nbody c\n\n"
    "## 2026-08-10 — older\n\nbody d\n\n"
    "## 2026-06-28 — Repository initialized\n\nbody e\n"
)


def test_lessons_archive_by_heading_date_and_never_the_newest_n():
    new, moved, n = cl.archive_lessons(LESSONS, date(2026, 10, 26), days=60, keep=3)
    assert n == 2 and "older" in moved and "Repository initialized" in moved
    assert "middle" in new and "newest" in new and "older" not in new
    assert new.rstrip().endswith(cl.POINTER_LESSONS)


def test_lessons_keep_protects_the_newest_even_when_all_are_old():
    _, moved, n = cl.archive_lessons(LESSONS, date(2030, 1, 1), days=60, keep=3)
    assert n == 2 and "newest" not in moved and "second" not in moved


def test_merge_archive_puts_newer_sections_first():
    first = cl._merge_archive(None, "# Archive", "intro", "## [b] — 2026-02-01\n\n- b\n")
    both = cl._merge_archive(first, "# Archive", "intro", "## [c] — 2026-03-01\n\n- c\n")
    assert both.index("[c]") < both.index("[b]")


def _repo(tmp_path, changelog=LOG, lessons=LESSONS):
    (tmp_path / "docs").mkdir()
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    (tmp_path / "docs" / "LESSONS_LEARNED.md").write_text(lessons, encoding="utf-8")
    return tmp_path


def test_cli_cut_check_and_refusals(tmp_path, capsys):
    root = _repo(tmp_path)
    assert cl.main(["--root", str(root), "check", "crucible", "1.8.0"]) == 1
    assert cl.main(["--root", str(root), "cut", "crucible", "1.8.0", "--date", "2026-11-01"]) == 0
    assert cl.main(["--root", str(root), "check", "crucible", "1.8.0"]) == 0
    assert cl.main(["--root", str(root), "cut", "crucible", "1.8.1"]) == 1        # empty now
    assert "empty" in capsys.readouterr().err


def test_cli_archive_is_a_dry_run_until_apply(tmp_path):
    root = _repo(tmp_path)
    before = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert cl.main(["--root", str(root), "archive", "--keep", "2", "--date", "2026-11-01"]) == 0
    assert (root / "CHANGELOG.md").read_text(encoding="utf-8") == before
    assert not (root / "docs" / "archive").exists()
    assert cl.main(["--root", str(root), "archive", "--keep", "2", "--date", "2026-11-01", "--apply"]) == 0
    arch = (root / "docs" / "archive" / "2026-11" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "[0.1.0]" in arch and "[0.1.0]" not in (root / "CHANGELOG.md").read_text(encoding="utf-8")


def test_cli_archive_lessons_apply(tmp_path):
    root = _repo(tmp_path)
    assert cl.main(["--root", str(root), "archive-lessons", "--date", "2026-10-26", "--apply"]) == 0
    assert "Repository initialized" in (root / "docs/archive/2026-10/LESSONS_LEARNED.md").read_text(encoding="utf-8")


def test_report_flags_archive_due_only_over_the_limit(tmp_path):
    big = LOG + "\n" + ("filler line\n" * 4000)
    out = "\n".join(cl.report(_repo(tmp_path, changelog=big), date(2026, 11, 1)))
    assert "ARCHIVE DUE: CHANGELOG.md" in out


def test_report_says_no_archive_due_for_small_files(tmp_path):
    out = "\n".join(cl.report(_repo(tmp_path), date(2026, 11, 1)))
    assert "no archive due" in out and "ARCHIVE DUE:" not in out


def test_report_lists_removal_candidates_as_unavailable_without_repo_metrics(tmp_path):
    out = "\n".join(cl.report(_repo(tmp_path), date(2026, 11, 1)))
    assert "unavailable" in out


# ----------------------------------------------------------- cms byte budgets (check.py)
def test_limits_match_the_cms_budget_check():
    """cms mirrors these limits; the two must not drift."""
    import common
    assert common.DOC_BUDGET_BYTES["CHANGELOG.md"] == cl.CHANGELOG_MAX_BYTES
    assert common.DOC_BUDGET_BYTES["docs/LESSONS_LEARNED.md"] == cl.LESSONS_MAX_BYTES


def test_doc_budget_warns_over_the_limit_and_is_silent_under_it(tmp_path):
    import check
    (tmp_path / "docs").mkdir()
    (tmp_path / "CHANGELOG.md").write_text("x" * 100, encoding="utf-8")
    assert check.check_doc_budgets(tmp_path) == []
    (tmp_path / "CHANGELOG.md").write_text("x" * 41_000, encoding="utf-8")
    (tmp_path / "docs" / "LESSONS_LEARNED.md").write_text("y" * 26_000, encoding="utf-8")
    found = check.check_doc_budgets(tmp_path)
    assert [f.level for f in found] == ["warning", "warning"]
    assert "41,000 bytes" in found[0].message and "docs/archive/YYYY-MM/" in found[0].message


def test_doc_budget_counts_bytes_not_lines(tmp_path):
    """The audit's case: 87 KB in 120 lines. Few lines, many bytes, still over."""
    import check
    (tmp_path / "CHANGELOG.md").write_text(("z" * 1000 + "\n") * 45, encoding="utf-8")
    assert len(check.check_doc_budgets(tmp_path)) == 1


def test_doc_budget_is_stateless(tmp_path, monkeypatch):
    import check
    saved = []
    monkeypatch.setattr(check, "save_state", lambda *a, **k: saved.append(a), raising=False)
    (tmp_path / "CHANGELOG.md").write_text("x" * 41_000, encoding="utf-8")
    check.check_doc_budgets(tmp_path)
    assert saved == []
