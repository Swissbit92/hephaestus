"""Clone-stable document ages, tested against real git repositories.

Every pre-existing test of the archive rule manufactured an old file with `os.utime`,
which is why the rule could be completely broken on every clone while the suite stayed
green: the tests asserted against a filesystem state that git never produces. **Nothing
in this file calls `os.utime`.** Ages here come from real commits with a real
`GIT_COMMITTER_DATE`, so a regression to mtime fails these tests immediately.
"""
from __future__ import annotations

import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

import add_frontmatter
import check
import doc_age
import migrate
from conftest import GitDocRepo


def second_repo(tmp_path: Path, name: str) -> GitDocRepo:
    """A repository alongside the `git_doc_repo` fixture, for the clone scenarios."""
    repo = tmp_path / name
    (repo / "docs").mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", name], cwd=str(tmp_path), check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return GitDocRepo(repo)


@pytest.fixture(autouse=True)
def _fresh_cache():
    """doc_age memoizes per repo root; every test here builds a different repository."""
    doc_age.clear_cache()
    yield
    doc_age.clear_cache()


# --------------------------------------------------------------- the core regression
def test_old_commit_beats_fresh_mtime(git_doc_repo):
    """The bug, stated as a test: mtime says today, git says 90 days, git must win."""
    f = git_doc_repo.commit("docs/MIGRATION_PLAN.md", "# Plan\n", age=90)

    assert date.fromtimestamp(f.stat().st_mtime) == date.today(), "precondition: mtime is fresh"

    days, changed, source = doc_age.age_days(f)
    assert source == doc_age.SOURCE_GIT
    assert 89 <= days <= 91, f"git-derived age was {days}"
    assert changed != date.today()


def test_old_committed_file_is_flagged_despite_fresh_mtime(git_doc_repo):
    """End to end through check.py — the finding the rule stopped producing on clones."""
    f = git_doc_repo.commit("docs/MIGRATION_PLAN.md", "# Plan\n", age=120)

    findings = check.check_archive_candidate(f)

    assert [x for x in findings if x.level == "warning"], "old committed plan was not flagged"
    assert "mtime" not in findings[0].message


def test_recently_committed_file_is_silent(git_doc_repo):
    f = git_doc_repo.commit("docs/MIGRATION_PLAN.md", "# Plan\n", age=5)
    assert check.check_archive_candidate(f) == []


# --------------------------------------------------------------- the prediction's check
def test_a_fresh_clone_agrees_with_the_original(tmp_path):
    """The property the whole change exists to buy.

    This is the check recorded against the `clone-stable-doc-age` prediction. Under the
    mtime implementation the clone reports zero findings while the original reports one,
    because cloning resets every mtime to checkout time — so this assertion is the
    difference between the rule working everywhere and working only where it was written.
    """
    origin = second_repo(tmp_path, "origin")
    origin.commit("docs/MIGRATION_PLAN.md", "# Plan\n", age=200)
    origin.commit("docs/RECENT_PLAN.md", "# Recent\n", age=3)

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", str(origin.path), str(clone)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def archive_findings(root: Path) -> set:
        doc_age.clear_cache()
        return {
            (Path(x.file).name, x.message.split(" per ")[0])
            for md in sorted(root.glob("docs/*.md"))
            for x in check.check_archive_candidate(md)
        }

    original = archive_findings(origin.path)
    cloned = archive_findings(clone)

    assert original == cloned, f"clone disagrees with origin:\n  origin={original}\n  clone={cloned}"
    assert len(original) == 1, "exactly the 200-day-old plan should be flagged"


# --------------------------------------------------------------- refusing to guess
def test_shallow_clone_disables_the_age_check_and_says_so(tmp_path):
    """A shallow clone collapses every path onto the graft commit, so every file looks
    like it changed today — the mtime failure wearing a git costume. Refuse, loudly."""
    origin = second_repo(tmp_path, "origin")
    origin.commit("docs/OLD_PLAN.md", "# Old\n", age=300)
    origin.commit("docs/NEWER_PLAN.md", "# Newer\n", age=10)

    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "--quiet", "--depth", "1",
                    "file://" + origin.path.as_posix(), str(shallow)],
                   check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    doc_age.clear_cache()
    usable, reason = doc_age.age_source_status(shallow)
    assert not usable
    assert "shallow" in reason.lower()
    assert "fetch-depth" in reason, "the message must name the fix, not just the fault"

    notices = check.check_doc_age_source(shallow)
    assert len(notices) == 1 and notices[0].level == "info"

    # And it must not invent findings out of the graft commit.
    assert check.check_archive_candidate(shallow / "docs" / "OLD_PLAN.md") == []


def test_outside_a_repo_falls_back_to_frontmatter_never_mtime(tmp_path):
    plain = tmp_path / "plain"
    (plain / "docs").mkdir(parents=True)
    old = plain / "docs" / "OLD_PLAN.md"
    old.write_text("---\nstatus: active\ncreated: 2020-01-01\n"
                   "last_reviewed_on: 2020-01-01\n---\n\n# Old\n", encoding="utf-8")
    bare = plain / "docs" / "BARE_PLAN.md"
    bare.write_text("# No frontmatter\n", encoding="utf-8")

    doc_age.clear_cache()
    days, changed, source = doc_age.age_days(old)
    assert source == doc_age.SOURCE_FRONTMATTER
    assert changed == date(2020, 1, 1)
    assert [x for x in check.check_archive_candidate(old) if x.level == "warning"]

    # No git, no frontmatter, no answer — and therefore no finding. Never an mtime guess.
    days, changed, source = doc_age.age_days(bare)
    assert (days, changed, source) == (None, None, doc_age.SOURCE_UNKNOWN)
    assert check.check_archive_candidate(bare) == []


def test_uncommitted_edits_are_never_archive_candidates(git_doc_repo):
    """A file with pending changes is being worked on right now, whatever git's last
    commit for it says."""
    f = git_doc_repo.commit("docs/MIGRATION_PLAN.md", "# Plan\n", age=300)
    f.write_text("# Plan\n\nStill editing this.\n", encoding="utf-8")

    doc_age.clear_cache()
    days, _changed, source = doc_age.age_days(f)
    assert source == doc_age.SOURCE_WORKING_TREE
    assert days == 0
    assert check.check_archive_candidate(f) == []


# --------------------------------------------------------------- the documented clause
def test_status_completed_triggers_candidacy_without_a_filename_match(git_doc_repo):
    """SKILL.md has always documented `status: completed` OR filename-match. Only the
    filename half was implemented, while migrate.py wrote the status field itself."""
    f = git_doc_repo.commit("docs/notes.md",
                            "---\nstatus: completed\n---\n\n# Notes\n", age=100)

    findings = check.check_archive_candidate(f)

    assert [x for x in findings if x.level == "warning"]
    assert "status: completed" in findings[0].message


def test_status_completed_still_respects_the_age_threshold(git_doc_repo):
    f = git_doc_repo.commit("docs/notes.md",
                            "---\nstatus: completed\n---\n\n# Notes\n", age=7)
    assert check.check_archive_candidate(f) == []


def test_allowlisted_names_are_immune_to_the_status_clause(git_doc_repo):
    """Widening the trigger must not reach documents the allowlist protects."""
    f = git_doc_repo.commit("docs/ARCHITECTURE.md",
                            "---\nstatus: completed\n---\n\n# Arch\n", age=999)
    assert check.check_archive_candidate(f) == []


# --------------------------------------------------------------- migrate.py (first tests)
def test_migrate_agrees_with_check_on_the_same_files(git_doc_repo):
    """The two used to be independent implementations of one rule and could disagree."""
    git_doc_repo.commit("docs/OLD_PLAN.md", "# Old\n", age=200)
    git_doc_repo.commit("docs/NEW_PLAN.md", "# New\n", age=2)
    git_doc_repo.commit("docs/done.md", "---\nstatus: completed\n---\n\n# Done\n", age=200)
    git_doc_repo.commit("docs/keep.md", "---\nstatus: active\n---\n\n# Keep\n", age=200)

    doc_age.clear_cache()
    by_migrate = {p.name for p in migrate.find_archive_candidates(git_doc_repo.path)}
    by_check = {
        md.name for md in sorted(git_doc_repo.path.glob("docs/*.md"))
        if any(x.level == "warning" for x in check.check_archive_candidate(md))
    }

    assert by_migrate == by_check == {"OLD_PLAN.md", "done.md"}


def test_archive_destination_uses_the_commit_month_not_this_month(git_doc_repo):
    """The folder name is the archive's index. Deriving it from mtime meant every
    document archived after a clone filed itself under the current month."""
    f = git_doc_repo.commit("docs/OLD_PLAN.md", "# Old\n", age=200)

    doc_age.clear_cache()
    dest = migrate.archive_destination(git_doc_repo.path, f)
    expected = (date.today() - timedelta(days=200)).strftime("%Y-%m")

    assert dest.parent.name == expected
    assert dest.parent.name != date.today().strftime("%Y-%m"), "200 days ago is not this month"


# --------------------------------------------------------------- add_frontmatter.py
def test_infer_created_uses_the_first_commit_not_the_last(git_doc_repo):
    git_doc_repo.commit("docs/notes.md", "# Notes\n", age=300)
    f = git_doc_repo.commit("docs/notes.md", "# Notes\n\nMore.\n", age=10)

    doc_age.clear_cache()
    first, source = doc_age.first_committed(f)
    last, _ = doc_age.last_changed(f)

    assert source == doc_age.SOURCE_GIT
    assert first < last, "first_committed must not return the newest commit"
    assert add_frontmatter.infer_created(f) == first.isoformat()


def test_infer_created_never_returns_an_mtime_derived_date(git_doc_repo):
    """The persisted-wrong-date bug: mtime is today, the file is 300 days old."""
    f = git_doc_repo.commit("docs/notes.md", "# Notes\n", age=300)

    doc_age.clear_cache()
    created = add_frontmatter.infer_created(f)

    assert created != date.today().isoformat()
    assert created == (date.today() - timedelta(days=300)).isoformat()
