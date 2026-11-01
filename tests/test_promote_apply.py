"""`integrate.py promote --apply`: the release route as a few explicit steps, with the
external ones behind a plan id.

The contract being pinned, and why:

  * `promote` alone stays a read-only plan. `--apply <step>` is the only way it acts.
  * The script runs local, reversible steps itself (`branch`, `prepare`) and the two external
    ones (`push`, `open-pr`) only when `--confirm` carries the id of the plan it would
    execute *now*. The id is recomputed from a fresh read, so a plan that went stale (a
    branch moved since it was shown) is refused with its own exit code, 4.
  * The id is a STALENESS guard, not authorization — an agent can compute it. The
    authorization is the user's go in conversation for that exact action. What the id buys
    is that "go" can never be spent on a different plan than the one that was shown.
  * It never merges, tags or publishes, never force-pushes, never touches `main`.

Every test drives the real script in a throwaway repo with a bare local `origin`; the
`prepare` / `open_pr` / `pr_view` declarations are stub argvs, so nothing touches a network
or a real forge.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "plugins" / "crucible" / "scripts" / "integrate.py"

sys.path.insert(0, str(REPO_ROOT / "evals"))
import fixtures  # noqa: E402
from test_integrate import _run  # noqa: E402  (same subprocess driver as the promote tests)

PLUGIN, VERSION = "x", "1.2.3"
BRANCH = f"release/{PLUGIN}-v{VERSION}"
SET = ["--set", f"plugin={PLUGIN}", "--set", f"version={VERSION}"]

_PREPARE_STUB = """import subprocess, sys
plugin, version = sys.argv[1], sys.argv[2]
open("VERSION", "w", encoding="utf-8").write(version + "\\n")
subprocess.run(["git", "add", "VERSION"], check=True)
subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=T",
                "commit", "-q", "-m", f"Release {plugin}-v{version}"], check=True)
"""

_FORGE_OPEN = ("import sys, pathlib; d = pathlib.Path(sys.argv[1]); d.mkdir(exist_ok=True); "
               "(d / sys.argv[2].replace('/', '_')).open('a').write('opened\\n')")
_RELEASE_SENTINEL = ("import sys, pathlib; d = pathlib.Path(sys.argv[1]); d.mkdir(exist_ok=True); "
                     "(d / 'RELEASED').write_text('the release command ran')")
_FORGE_VIEW = ("import sys, pathlib; p = pathlib.Path(sys.argv[1]) / sys.argv[2].replace('/', '_'); "
               "print('https://forge.invalid/pr/1' if p.exists() else '')")


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=T",
                        "-c", "commit.gpgsign=false", *args], cwd=str(repo), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=60)
    assert p.returncode == 0, (args, p.stdout, p.stderr)
    return p.stdout.strip()


def _declaration(forge: Path) -> dict:
    exe = sys.executable
    return {
        "from": "dev", "to": "main", "via": "pr",
        "prepare": [exe, "scripts/prepare_stub.py", "{plugin}", "{version}"],
        "open_pr": [exe, "-c", _FORGE_OPEN, forge.as_posix(), "{branch}"],
        "pr_view": [exe, "-c", _FORGE_VIEW, forge.as_posix(), "{branch}"],
        "command": [exe, "-c", _RELEASE_SENTINEL, forge.as_posix()],
    }


@pytest.fixture
def world(tmp_path):
    """A repo on `dev` (level with main) that has a bare `origin`, a release declaration made
    of stub argvs, and a `forge` directory standing in for the host's PRs."""
    forge = tmp_path / "forge"
    repo = fixtures.branched_repo(tmp_path / "r", {
        "README.md": "x\n",
        "scripts/prepare_stub.py": _PREPARE_STUB,
        ".crucible/release.json": json.dumps(_declaration(forge)),
    }, branch="dev-work")
    _git(repo, "switch", "-q", "dev")
    _git(repo, "branch", "-q", "-D", "dev-work")
    fixtures._with_origin(repo)          # bare origin with main and dev; leaves dev checked out
    return repo


def _origin(repo: Path) -> Path:
    return repo.parent / f"{repo.name}-origin.git"


def _forge(repo: Path) -> Path:
    return repo.parent / "forge"


def _remote_refs(origin: Path) -> str:
    return subprocess.run(["git", "ls-remote", str(origin)], capture_output=True, text=True,
                          encoding="utf-8").stdout


def _prepared_branch(repo: Path) -> None:
    """The release branch as `--apply branch` + `--apply prepare` would leave it, made with
    plain git so the push tests do not depend on those steps."""
    _git(repo, "switch", "-q", "-c", BRANCH, "dev")
    (repo / "VERSION").write_text(VERSION + "\n", encoding="utf-8")
    _git(repo, "add", "VERSION")
    _git(repo, "commit", "-q", "-m", f"Release {PLUGIN}-v{VERSION}")


def _dev_moves_on(repo: Path, push: bool = True) -> None:
    """`dev` gains a commit after a plan / release branch existed (and, by default, so does origin)."""
    _git(repo, "switch", "-q", "dev")
    (repo / "later.txt").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-q", "-m", "dev moved on")
    if push:
        _git(repo, "push", "-q", "origin", "dev")


def _plan_id(repo: Path) -> str:
    code, out = _run(repo, "promote", *SET)
    m = re.search(r"^\s*plan: ([0-9a-f]{12})\b", out, re.M)
    assert m, f"`promote` printed no plan id (exit {code}):\n{out}"
    return m.group(1)


# ================================================== the prediction (PR for this task)
def test_push_refuses_without_confirm_and_changes_nothing_on_the_remote(world):
    _prepared_branch(world)
    before = _remote_refs(_origin(world))
    code, out = _run(world, "promote", "--apply", "push", *SET)
    assert code == 2 and "--confirm" in out, out
    assert _remote_refs(_origin(world)) == before, "a refused push must not touch the remote"


def test_push_refuses_a_stale_plan_id_with_its_own_exit_code(world):
    _prepared_branch(world)
    stale = _plan_id(world)
    # `dev` moves on after the plan was shown: the id no longer describes what would be pushed.
    _dev_moves_on(world, push=False)
    _git(world, "switch", "-q", BRANCH)
    before = _remote_refs(_origin(world))
    code, out = _run(world, "promote", "--apply", "push", "--confirm", stale, *SET)
    assert code == 4, out
    assert stale in out, "the refusal must show the old id next to the new one"
    assert _remote_refs(_origin(world)) == before, "a stale plan must not touch the remote"


# ============================================================ M1: the plan and its id
def test_plan_mode_is_unchanged_without_plugin_and_version(world):
    """Plain `promote` keeps working with only what it always needed; the id and the release
    branch need `plugin` and `version` (they name the branch)."""
    code, out = _run(world, "promote", "--set", f"version={VERSION}", "--set", f"plugin={PLUGIN}")
    assert code == 0 and "dev -> main via pr" in out and "explicit go" in out
    # a declaration with no prepare/open_pr must not be asked for placeholders it lacks
    fixtures._write(world, ".crucible/release.json",
                    json.dumps({"from": "dev", "to": "main", "dry_run": [sys.executable, "-c", "print('dry')"]}))
    code, out = _run(world, "promote")
    assert code == 0 and "plan:" not in out and "release branch" not in out


def test_the_plan_names_the_branch_the_prepare_step_and_an_id(world):
    code, out = _run(world, "promote", *SET)
    assert code == 0, out
    assert f"release branch: {BRANCH} (tip not created yet)" in out
    assert "prepare (local, one commit)" in out and "prepare_stub.py" in out
    assert re.search(r"^\s*plan: [0-9a-f]{12}$", out, re.M)


def test_the_id_moves_with_everything_the_plan_acts_on(world):
    """If any of these changed, an approval given for the earlier plan must not carry over."""
    first = _plan_id(world)
    assert _plan_id(world) == first, "the id is a pure function of the facts"

    _prepared_branch(world)                                   # the branch now exists
    with_branch = _plan_id(world)
    assert with_branch != first

    (world / "VERSION").write_text("changed\n", encoding="utf-8")
    _git(world, "commit", "-aq", "-m", "the release commit changed")   # a different commit
    assert _plan_id(world) != with_branch, "the id binds the exact commit that would be pushed"

    other = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(world), "promote",
                            "--set", f"plugin={PLUGIN}", "--set", "version=9.9.9"],
                           capture_output=True, text=True, encoding="utf-8").stdout
    assert re.search(r"plan: ([0-9a-f]{12})", other).group(1) not in (first, with_branch)


def test_open_pr_and_pr_view_are_validated_like_the_other_argvs(world):
    fixtures._write(world, ".crucible/release.json",
                    json.dumps({"from": "dev", "to": "main", "open_pr": "gh pr create", "pr_view": []}))
    code, out = _run(world, "promote")
    assert code == 2 and "'open_pr'" in out and "'pr_view'" in out


# =========================================== M2: --apply, --confirm and the stale exit
def test_an_external_step_needs_a_confirm_and_says_what_it_is_and_is_not(world):
    for step in ("push", "open-pr"):
        code, out = _run(world, "promote", "--apply", step, *SET)
        assert code == 2, (step, out)
        assert "--confirm" in out and "explicit go" in out and "has not changed" in out, out


def test_a_wrong_id_is_stale_whatever_the_step_and_nothing_runs(world):
    _prepared_branch(world)
    before = _remote_refs(_origin(world))
    for step in ("push", "open-pr"):
        code, out = _run(world, "promote", "--apply", step, "--confirm", "0" * 12, *SET)
        assert code == 4 and "STALE PLAN" in out and "0" * 12 in out, (step, out)
    assert _remote_refs(_origin(world)) == before
    assert not _forge(world).exists(), "a refused open-pr must not reach the forge"


def test_apply_needs_plugin_and_version_to_name_the_branch(world):
    code, out = _run(world, "promote", "--apply", "branch")
    assert code == 2 and "--set plugin" in out and "--set version" in out


def test_apply_without_a_declaration_is_a_skip_not_a_guess(world):
    (world / ".crucible" / "release.json").unlink()
    _git(world, "commit", "-aq", "-m", "no declaration")
    code, out = _run(world, "promote", "--apply", "branch", *SET)
    assert code == 3 and "SKIP" in out


def test_an_unknown_step_is_rejected_by_the_parser(world):
    code, out = _run(world, "promote", "--apply", "merge", *SET)
    assert code == 2 and "invalid choice" in out, "there is deliberately no merge (or tag) step"
    code, out = _run(world, "promote", "--apply", "release", *SET)
    assert code == 2 and "invalid choice" in out


# ================================================== M3: the local steps, and resuming them
def _head_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def _ahead_of(repo: Path, base: str = "dev") -> int:
    return int(_git(repo, "rev-list", "--count", f"{base}..HEAD"))


def _edit_declaration(repo: Path, **changes) -> None:
    """Change keys of .crucible/release.json (None deletes one), commit it on dev and push dev,
    so local dev stays level with origin/dev."""
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "dev", \
        "edit the declaration on dev, before cutting the release branch (it would move the branch tip)"
    path = repo / ".crucible" / "release.json"
    decl = json.loads(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            decl.pop(key, None)
        else:
            decl[key] = value
    path.write_text(json.dumps(decl), encoding="utf-8")
    _git(repo, "commit", "-aq", "-m", "edit the release declaration")
    _git(repo, "push", "-q", "origin", "dev")


def _declare_prepare(repo: Path, argv) -> None:
    _edit_declaration(repo, prepare=argv)


def _prepare_with(repo: Path, argv):
    """Declare `argv` as the prepare step, cut the release branch, and run `--apply prepare`."""
    _declare_prepare(repo, argv)
    _run(repo, "promote", "--apply", "branch", *SET)
    return _run(repo, "promote", "--apply", "prepare", *SET)


def test_branch_cuts_the_release_branch_off_dev_and_pushes_nothing(world):
    before = _remote_refs(_origin(world))
    code, out = _run(world, "promote", "--apply", "branch", *SET)
    assert code == 0 and f"created {BRANCH}" in out, out
    assert _head_branch(world) == BRANCH
    assert _git(world, "rev-parse", "HEAD") == _git(world, "rev-parse", "dev")
    assert _remote_refs(_origin(world)) == before, "a local step must not touch the remote"


def test_branch_is_idempotent(world):
    assert _run(world, "promote", "--apply", "branch", *SET)[0] == 0
    code, out = _run(world, "promote", "--apply", "branch", *SET)
    assert code == 0 and "already done" in out, out
    assert _git(world, "branch", "--list", "release/*").count("release/") == 1


def test_branch_refuses_a_dirty_tree_and_creates_nothing(world):
    (world / "README.md").write_text("changed\n", encoding="utf-8")
    code, out = _run(world, "promote", "--apply", "branch", *SET)
    assert code == 1 and "not clean" in out, out
    assert _git(world, "branch", "--list", BRANCH) == ""


def test_branch_refuses_when_local_dev_is_behind_origin(world):
    """Judged after a fetch, so it is not fooled by a stale remote-tracking ref."""
    _git(world, "switch", "-q", "-c", "elsewhere", "dev")
    (world / "other.txt").write_text("x\n", encoding="utf-8")
    _git(world, "add", "other.txt")
    _git(world, "commit", "-q", "-m", "someone else's work on dev")
    _git(world, "push", "-q", "origin", "elsewhere:dev")
    _git(world, "switch", "-q", "dev")
    code, out = _run(world, "promote", "--apply", "branch", *SET)
    assert code == 1 and "not level with origin/dev" in out, out
    assert _git(world, "branch", "--list", BRANCH) == ""


def test_branch_refuses_an_existing_branch_that_lacks_dev(world):
    assert _run(world, "promote", "--apply", "branch", *SET)[0] == 0
    _dev_moves_on(world)
    code, out = _run(world, "promote", "--apply", "branch", *SET)
    assert code == 1 and "does not contain 'dev'" in out and "will not move or delete" in out, out


def test_prepare_makes_exactly_one_commit_and_prints_the_new_id(world):
    _run(world, "promote", "--apply", "branch", *SET)
    old_id = _plan_id(world)
    before = _remote_refs(_origin(world))
    code, out = _run(world, "promote", "--apply", "prepare", *SET)
    assert code == 0 and "prepared: one commit" in out, out
    assert _ahead_of(world) == 1 and _git(world, "status", "--porcelain") == ""
    assert _git(world, "log", "-1", "--format=%s") == f"Release {PLUGIN}-v{VERSION}"
    new_id = re.search(r"plan: ([0-9a-f]{12})", out).group(1)
    assert new_id != old_id and new_id == _plan_id(world), "the printed id is the one push will need"
    assert _remote_refs(_origin(world)) == before


def test_prepare_is_idempotent(world):
    _run(world, "promote", "--apply", "branch", *SET)
    assert _run(world, "promote", "--apply", "prepare", *SET)[0] == 0
    code, out = _run(world, "promote", "--apply", "prepare", *SET)
    assert code == 0 and "already prepared" in out and _ahead_of(world) == 1, out


def test_prepare_refuses_the_wrong_branch_and_a_dirty_tree(world):
    code, out = _run(world, "promote", "--apply", "prepare", *SET)          # still on dev
    assert code == 1 and "not on release/" in out and "--apply branch" in out, out
    _run(world, "promote", "--apply", "branch", *SET)
    (world / "README.md").write_text("changed\n", encoding="utf-8")
    code, out = _run(world, "promote", "--apply", "prepare", *SET)
    assert code == 1 and "not clean" in out and _ahead_of(world) == 0, out


def test_a_failing_prepare_is_reported_with_its_output(world):
    code, out = _prepare_with(world, [sys.executable, "-c", "import sys; print('boom: bad changelog'); sys.exit(7)"])
    assert code == 1 and "exit 7" in out and "boom: bad changelog" in out, out
    assert _ahead_of(world) == 0


def test_a_prepare_that_exits_zero_but_makes_no_commit_is_not_a_pass(world):
    code, out = _prepare_with(world, [sys.executable, "-c", "pass"])
    assert code == 1 and "did not advance" in out and _ahead_of(world) == 0, out


def test_a_prepare_that_makes_two_commits_is_not_a_pass(world):
    """One release commit is the contract: a second one would ride along into the PR."""
    script = ("import subprocess as s; g=['git','-c','user.email=t@e.invalid','-c','user.name=T']\n"
              "for n in ('a','b'):\n"
              "    open(n,'w').write(n); s.run(g+['add',n],check=True); "
              "s.run(g+['commit','-q','-m','Release '+n],check=True)")
    code, out = _prepare_with(world, [sys.executable, "-c", script])
    assert code == 1 and "expected exactly one commit" in out and "2 new commit" in out, out


def test_prepare_without_a_declared_argv_is_a_skip(world):
    decl = json.loads((world / ".crucible" / "release.json").read_text(encoding="utf-8"))
    del decl["prepare"]
    (world / ".crucible" / "release.json").write_text(json.dumps(decl), encoding="utf-8")
    _git(world, "commit", "-aq", "-m", "no prepare")
    _git(world, "push", "-q", "origin", "dev")
    _run(world, "promote", "--apply", "branch", *SET)
    code, out = _run(world, "promote", "--apply", "prepare", *SET)
    assert code == 3 and "SKIP" in out and "no 'prepare'" in out, out


# ===================================== M3 review findings: stale base, where the commit lands
def test_prepare_refuses_a_branch_that_fell_behind_dev(world):
    """The branch was cut, then dev moved: `rev-list from..HEAD` counts 0 for a branch that
    merely lacks dev's new commit, so only an ancestry check notices the stale base."""
    _run(world, "promote", "--apply", "branch", *SET)
    _dev_moves_on(world)
    _git(world, "switch", "-q", BRANCH)
    code, out = _run(world, "promote", "--apply", "prepare", *SET)
    assert code == 1 and "does not contain 'dev'" in out, out
    assert _ahead_of(world) == 0 and not (world / "VERSION").exists(), "prepare must not have run"


def test_a_prepare_that_commits_on_another_branch_is_not_a_pass(world):
    """Counts and a clean tree look right when the argv switched branches and committed there;
    only re-reading HEAD and the branch tip catches it."""
    script = ("import subprocess as s; g=['git','-c','user.email=t@e.invalid','-c','user.name=T']; "
              "s.run(g+['switch','-q','-c','somewhere-else'],check=True); open('V','w').write('1'); "
              "s.run(g+['add','V'],check=True); s.run(g+['commit','-q','-m','Release x'],check=True)")
    code, out = _prepare_with(world, [sys.executable, "-c", script])
    assert code == 1 and "did not advance" in out and BRANCH in out, out


def test_a_hostile_set_value_is_refused_before_git_sees_it(world):
    for bad in ("1 2", "../x", "a@{1}", "1.0^", "a:b"):
        code, out = _run(world, "promote", "--apply", "branch", "--set", f"plugin={PLUGIN}",
                         "--set", f"version={bad}")
        assert code == 2 and "not a valid branch name" in out, (bad, out)
    assert _git(world, "branch", "--list", "release/*") == ""


def test_the_printed_command_is_the_one_in_the_id(world):
    """Plan mode used to fill `command` from the raw --set values and the id from the derived
    ones, so `--set from=x` could print one line and hash another."""
    decl = json.loads((world / ".crucible" / "release.json").read_text(encoding="utf-8"))
    decl["command"] = [sys.executable, "-c", "print('{from}->{to}')"]
    (world / ".crucible" / "release.json").write_text(json.dumps(decl), encoding="utf-8")
    _git(world, "commit", "-aq", "-m", "command uses from/to")
    _git(world, "push", "-q", "origin", "dev")
    code, out = _run(world, "promote", *SET, "--set", "from=SHOULD-NOT-WIN")
    assert "dev->main" in out and "SHOULD-NOT-WIN" not in out.split("plan:")[0].split("2.")[1], out


# =========================================== M4: the external steps, behind --confirm
def _confirmed(repo: Path, step: str):
    return _run(repo, "promote", "--apply", step, "--confirm", _plan_id(repo), *SET)


def _prepared_by_the_script(repo: Path) -> None:
    for step in ("branch", "prepare"):
        code, out = _run(repo, "promote", "--apply", step, *SET)
        assert code == 0, (step, out)


def _pushed(repo: Path) -> None:
    _prepared_by_the_script(repo)
    code, out = _confirmed(repo, "push")
    assert code == 0, out


def _forge_log(repo: Path) -> list:
    path = _forge(repo) / BRANCH.replace("/", "_")
    return path.read_text(encoding="utf-8").split() if path.exists() else []


def test_push_pushes_the_release_branch_and_nothing_else(world):
    _prepared_by_the_script(world)
    before = _remote_refs(_origin(world)).splitlines()
    code, out = _confirmed(world, "push")
    assert code == 0 and "pushed" in out and "fresh read" in out, out
    after = _remote_refs(_origin(world)).splitlines()
    added = [ln for ln in after if ln not in before]
    assert len(added) == 1 and added[0].endswith(f"refs/heads/{BRANCH}"), added
    assert added[0].split()[0] == _git(world, "rev-parse", BRANCH), "the exact prepared commit"
    assert all(ln in after for ln in before), "main and dev on origin are untouched"
    assert not [ln for ln in after if "refs/tags" in ln], "a tag is never pushed"


def test_push_is_idempotent(world):
    _pushed(world)
    code, out = _confirmed(world, "push")
    assert code == 0 and "already pushed" in out, out


def test_push_never_forces_over_a_diverged_remote(world):
    _pushed(world)
    remote_before = _remote_refs(_origin(world))
    _git(world, "commit", "-q", "--amend", "-m", f"Release {PLUGIN}-v{VERSION} (amended)")
    code, out = _confirmed(world, "push")            # the id is current for the amended commit
    assert code == 1 and "never force-pushes" in out, out
    assert _remote_refs(_origin(world)) == remote_before


def test_push_refuses_when_nothing_is_prepared(world):
    code, out = _confirmed(world, "push")            # no release branch at all
    assert code == 1 and "no release/" in out and "--apply branch" in out, out
    _run(world, "promote", "--apply", "branch", *SET)
    code, out = _confirmed(world, "push")            # branch, but no release commit
    assert code == 1 and "prepared release branch" in out, out
    assert _git(world, "ls-remote", "--heads", "origin", BRANCH) == ""


def test_open_pr_runs_the_declared_argv_once_and_reads_the_pr_back(world):
    _pushed(world)
    code, out = _confirmed(world, "open-pr")
    assert code == 0 and "opened a PR" in out and "MERGE COMMIT" in out, out
    assert _forge_log(world) == ["opened"]
    code, out = _confirmed(world, "open-pr")
    assert code == 0 and "already open" in out, out
    assert _forge_log(world) == ["opened"], "a second run must not open a second PR"


def test_open_pr_needs_the_branch_on_origin_first(world):
    _prepared_by_the_script(world)
    code, out = _confirmed(world, "open-pr")
    assert code == 1 and "--apply push" in out, out
    assert not _forge(world).exists()


def test_open_pr_assumes_no_forge(world):
    _edit_declaration(world, open_pr=None)
    _pushed(world)
    code, out = _confirmed(world, "open-pr")
    assert code == 3 and "no forge is assumed" in out and "never a squash" in out, out
    assert not _forge(world).exists()


def test_open_pr_without_a_pr_view_cannot_be_idempotent_so_it_does_not_run(world):
    _edit_declaration(world, pr_view=None)
    _pushed(world)
    code, out = _confirmed(world, "open-pr")
    assert code == 3 and "'pr_view'" in out, out
    assert not _forge(world).exists()


def test_a_pr_that_cannot_be_read_back_is_not_a_pass(world):
    _edit_declaration(world, open_pr=[sys.executable, "-c", "pass"])      # "succeeds", opens nothing
    _pushed(world)
    code, out = _confirmed(world, "open-pr")
    assert code == 2 and "cannot find a PR" in out, out


def test_a_failing_open_pr_is_reported_with_its_output(world):
    _edit_declaration(world, open_pr=[sys.executable, "-c", "import sys; print('forge says no'); sys.exit(5)"])
    _pushed(world)
    code, out = _confirmed(world, "open-pr")
    assert code == 1 and "exit 5" in out and "forge says no" in out, out


def test_the_whole_route_never_merges_tags_or_runs_the_release_command(world):
    refs_before = _remote_refs(_origin(world)).splitlines()
    _pushed(world)
    assert _confirmed(world, "open-pr")[0] == 0
    after = _remote_refs(_origin(world)).splitlines()
    assert [ln for ln in after if ln not in refs_before][0].endswith(f"refs/heads/{BRANCH}")
    assert len(after) == len(refs_before) + 1, "exactly one new ref on origin: the release branch"
    assert all(ln in after for ln in refs_before), "main and dev on origin did not move"
    assert _git(world, "tag", "--list") == "" and not [ln for ln in after if "refs/tags" in ln]
    assert not (_forge(world) / "RELEASED").exists(), "the declared release command was executed"


# ===================================== M4 review findings: what the plan shows, and how a push runs
def test_the_plan_shows_every_command_that_confirm_can_make_the_script_run(world):
    """The id proves the plan did not change; it cannot tell the user what the plan IS. So every
    argv `--confirm` can execute must be printed in full — including the declared open_pr and
    pr_view, which come from a file a merged PR can edit."""
    code, out = _run(world, "promote", *SET)
    assert code == 0, out
    forge = _forge(world).as_posix()
    assert f"push (external, needs --confirm): git push -u origin refs/heads/{BRANCH}:refs/heads/{BRANCH}" in out
    decl = _declaration(_forge(world))
    assert "open-pr (external, needs --confirm): " + " ".join(a.replace("{branch}", BRANCH) for a in decl["open_pr"]) in out
    assert "pr-view (read-only lookup): " + " ".join(a.replace("{branch}", BRANCH) for a in decl["pr_view"]) in out
    assert forge in out


def test_a_declared_open_pr_that_changes_changes_the_id(world):
    """An edited open_pr is a different plan: an approval for the old argv cannot be spent on it."""
    before = _plan_id(world)
    _edit_declaration(world, open_pr=[sys.executable, "-c", "print('something else')"])
    assert _plan_id(world) != before


def test_a_pr_lookup_that_errors_is_not_read_as_no_pr(world):
    """`gh pr view` exits 1 both for 'no PR' and for an auth failure; reading an error as 'absent'
    would open a duplicate. The contract: exit 0 + empty output = none; non-zero = unknown."""
    _edit_declaration(world, pr_view=[sys.executable, "-c", "import sys; print('HTTP 401', file=sys.stderr); sys.exit(3)"])
    _pushed(world)
    code, out = _confirmed(world, "open-pr")
    assert code == 2 and "pr_view exited 3" in out and "HTTP 401" in out, out
    assert not _forge(world).exists(), "open_pr must not run when the lookup could not answer"


@pytest.mark.skipif(sys.platform == "win32", reason="a sh shim stands in for git on PATH")
def test_the_push_command_is_exactly_one_explicit_refspec_with_no_force(world, tmp_path):
    """Mutation found by review: adding --force survived because the ancestry guard refuses first.
    It is reachable only through a race (origin moves between the check and the push), which a
    test cannot stage — so pin the argv itself."""
    import shutil
    _prepared_by_the_script(world)
    log, shim = tmp_path / "git-argv.log", tmp_path / "shim"
    shim.mkdir()
    (shim / "git").write_text('#!/bin/sh\necho "$@" >> "$GIT_ARGV_LOG"\nexec "$REAL_GIT" "$@"\n', encoding="utf-8")
    (shim / "git").chmod(0o755)
    import os
    env = dict(os.environ, PATH=str(shim) + os.pathsep + os.environ["PATH"], GIT_ARGV_LOG=str(log),
               REAL_GIT=shutil.which("git"))
    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(world), "promote", "--apply", "push",
                        "--confirm", _plan_id(world), *SET], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    pushes = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.startswith("push")]
    assert pushes == [f"push -u origin refs/heads/{BRANCH}:refs/heads/{BRANCH}"], pushes
    assert not re.search(r"--force|--mirror|--tags|--delete|(^| )-f( |$)|\+refs", pushes[0])


# ============================================================ M6: this repo dogfoods the route
def test_this_repos_declaration_describes_the_whole_route():
    """The repo's own `.crucible/release.json` must carry every argv the route runs, resolve to
    the right branch, and keep the pr_view contract (print nothing when there is no PR)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("integrate", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPT.parent))
    spec.loader.exec_module(mod)
    decl = mod.load_declaration(REPO_ROOT)
    facts = mod.release_facts(REPO_ROOT, decl, {"plugin": "crucible", "version": "9.9.9"})
    assert facts["branch"] == "release/crucible-v9.9.9" and (facts["from"], facts["to"]) == ("dev", "main")
    argv = facts["argv"]
    assert "--prepare" in argv["prepare"] and argv["prepare"][:2] == ["scripts/release.sh", "crucible"]
    assert argv["open_pr"][:3] == ["gh", "pr", "create"] and "--base" in argv["open_pr"]
    assert argv["open_pr"][argv["open_pr"].index("--head") + 1] == "release/crucible-v9.9.9"
    # `gh pr list` + `// empty`: exit 0 and no output when there is no PR (`gh pr view` cannot say that)
    assert argv["pr_view"][:3] == ["gh", "pr", "list"] and argv["pr_view"][-1] == ".[0].url // empty"
    assert "merge" not in " ".join(argv["open_pr"] + argv["pr_view"] + argv["prepare"]), \
        "no declared argv merges anything"


# ================================================== a hung push is "could not determine"
@pytest.mark.skipif(sys.platform == "win32", reason="a sh pre-push hook stands in for a hung credential prompt")
def test_a_hung_push_is_could_not_determine_not_a_plain_failure(world):
    """A push that hangs (a credential prompt, a stalled network) and is killed must not read as
    'git push failed': it may or may not have reached the remote, so the answer is exit 2 —
    and a re-run must recover, because the next run reads origin first."""
    import importlib.util
    import time
    spec = importlib.util.spec_from_file_location("integrate_for_timeout", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPT.parent))
    spec.loader.exec_module(mod)

    _prepared_by_the_script(world)
    hook = world / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\nsleep 20\n", encoding="utf-8")
    hook.chmod(0o755)
    mod.PUSH_TIMEOUT = 1                      # the real limit is 120 s; the test must not wait for it
    values = {"plugin": PLUGIN, "version": VERSION}
    plan = mod.plan_id(mod.release_facts(world, mod.load_declaration(world), values))

    started = time.monotonic()
    with pytest.raises(mod.Undetermined) as excinfo:
        mod.apply_step(world, "push", values, plan)
    assert "was stopped (timeout)" in str(excinfo.value) and "git push" in str(excinfo.value)
    assert time.monotonic() - started < 15, "the hung push must be killed, not waited out"
    assert _git(world, "ls-remote", "--heads", "origin", BRANCH) == "", "nothing reached the remote"

    hook.unlink()                             # the prompt is answered / the network is back
    code, out = _confirmed(world, "push")
    assert code == 0 and "pushed" in out, out
    assert _git(world, "ls-remote", "--heads", "origin", BRANCH).split()[0] == _git(world, "rev-parse", BRANCH)
