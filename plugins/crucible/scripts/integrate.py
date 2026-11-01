#!/usr/bin/env python3
"""What integrating and promoting this branch should look like — advice and plans, never
the irreversible step itself.

  recommend   For finish-branch: should integration go through a pull request? Yes when
              the target runs CI (its own tree, not this branch's) or the remote protects
              it, because only a PR gets the change checked on the merged tree before it
              lands. No remote → a PR is impossible, so the plain options stand. Prints one
              line, `RECOMMEND: pr (...)` or `RECOMMEND: choose (...)`. It recommends; the
              user still chooses — nothing here pushes, opens or merges.

  promote     After integration: the repo's DECLARED release path, from `.crucible/release.json`
              ({"from": "dev", "to": "main", "via": "pr"|"merge", "command": [...],
              "dry_run": [...]}; `{name}` placeholders filled with --set name=value). Prints
              the plan and runs only `dry_run`. The release `command` pushes and publishes,
              so it is never run here: it is the user's explicit go, for that exact action,
              and the result is confirmed from a fresh read (act-for-real). Release tools a
              repo uses instead (release-please, changesets, semantic-release) are detected
              and reported — they release from CI, so the promote step is a PR into `to`.

The plugin ships the contract; the repo ships the release process. Nothing is invented: no
declaration and no detected tool is a SKIP, not a guess.

  promote --apply STEP   Run ONE step of the release route, only for a repo that declares it.
              branch    cut release/<plugin>-v<version> off `from`       (local, reversible)
              prepare   run the declared `prepare` argv on that branch    (local, one commit)
              push      push that branch to origin — never main, never a tag, never --force
              open-pr   run the declared `open_pr` argv (no forge is assumed)
              `push` and `open-pr` act outside this checkout, so they need `--confirm ID` where
              ID is the `plan:` line `promote` printed. The id is recomputed from the current refs
              and a stale one is refused (exit 4). It is a STALENESS guard, not authorization:
              anyone can compute it. The user's explicit go for that exact action is the
              authorization, and a go for one plan is never spent on another. Merging, tagging
              and publishing are NOT steps here — merge stays the human gate, and the release
              command stays a printed line for `release.sh` on the target branch.

Exit codes: 0 advice/plan printed (and the dry run passed) / the step done or already done ·
1 the declared dry run failed or a step refused (dirty tree, diverged branch) ·
2 could not determine (no target, malformed declaration, missing placeholder, missing
--confirm, a result that could not be read back) · 3 nothing declared or detected — a SKIP ·
4 the plan changed since its id was shown (stale --confirm).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crucible_common import (  # noqa: E402
    detect_ci,
    detect_target,
    git_out,
    remote_ref,
    run,
    run_bounded,
    utf8_stdio,
)

RELEASE_TOOLS = (
    ("release-please-config.json", "release-please"),
    (".release-please-manifest.json", "release-please"),
    (".changeset", "changesets"),
    (".releaserc", "semantic-release"),
    (".releaserc.json", "semantic-release"),
    (".releaserc.yml", "semantic-release"),
    ("release.config.js", "semantic-release"),
)


class Undetermined(Exception):
    pass


class Skip(Exception):
    pass


class Stale(Exception):
    """--confirm names a plan that is no longer the current one."""


# --------------------------------------------------------------------------- recommend
def protected(repo: Path, branch: str) -> bool | None:
    """Best effort via the GitHub CLI; None when it cannot be asked (no gh, not GitHub,
    no auth). Protection is only a second reason — CI on the target is the first."""
    if not shutil.which("gh"):
        return None
    try:
        p = subprocess.run(["gh", "api", f"repos/{{owner}}/{{repo}}/branches/{branch}/protection"],
                           cwd=str(repo), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode == 0:
        return True
    return False if "Branch not protected" in (p.stdout + p.stderr) else None


def recommend(repo: Path, target: str | None, ask_remote: bool) -> str:
    t = detect_target(repo, target)
    if not t:
        raise Undetermined("cannot determine: no integration target found; pass --target")
    ref = remote_ref(repo, t)
    if ref is None:
        return f"RECOMMEND: choose (no remote branch for {t} — a pull request is not possible here)"
    ci = detect_ci(repo, ref)
    if ci is None:
        raise Undetermined(f"cannot determine: could not read the tree of {ref}")
    if ci:
        return f"RECOMMEND: pr (ci: {', '.join(ci)} on {t} — only a PR runs it on the merged tree)"
    prot = protected(repo, t) if ask_remote else None
    if prot:
        return f"RECOMMEND: pr ({t} is protected on the remote)"
    note = "" if prot is False else "; protection not checked"
    return f"RECOMMEND: choose (no CI found on {t}{note})"


# --------------------------------------------------------------------------- promote
def load_declaration(repo: Path) -> dict | None:
    path = repo / ".crucible" / "release.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise Undetermined(f"cannot determine: {path.as_posix()} is not valid JSON") from None
    problems = []
    if not isinstance(data, dict):
        raise Undetermined(f"cannot determine: {path.as_posix()} must be a JSON object")
    for key in ("from", "to"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            problems.append(f"'{key}' must be a non-empty branch name")
    if data.get("via", "pr") not in ("pr", "merge"):
        problems.append("'via' must be \"pr\" or \"merge\"")
    for key in ("prepare", "command", "dry_run", "open_pr", "pr_view"):
        if key in data and (not isinstance(data[key], list) or not data[key]
                            or not all(isinstance(x, str) for x in data[key])):
            problems.append(f"'{key}' must be a non-empty list of strings")
    if problems:
        raise Undetermined(f"cannot determine: {path.as_posix()}: " + "; ".join(problems))
    return data


def fill(argv: list[str], values: dict[str, str]) -> list[str]:
    out = []
    for arg in argv:
        missing = [n for n in re.findall(r"\{(\w+)\}", arg) if n not in values]
        if missing:
            raise Undetermined(f"cannot determine: placeholder {{{missing[0]}}} needs --set {missing[0]}=...")
        out.append(re.sub(r"\{(\w+)\}", lambda m: values[m.group(1)], arg))
    return out


def detected_tools(repo: Path) -> list[str]:
    return sorted({name for marker, name in RELEASE_TOOLS if (repo / marker).exists()})


# Declared argvs a plan can include, in the order the release route runs them.
PLAN_ARGVS = ("prepare", "open_pr", "pr_view", "command")


def _sha(repo: Path, ref: str) -> str:
    return git_out(repo, "rev-parse", "--verify", "--quiet", ref) or ""


def _contains(repo: Path, ancestor_sha: str, ref: str) -> bool:
    return run(["git", "merge-base", "--is-ancestor", ancestor_sha, ref], repo, timeout=60)[0] == 0


def _valid_branch(repo: Path, name: str) -> None:
    """A --set value or a declared branch name is untrusted input to git: refuse anything git
    itself would not accept as a branch (spaces, '..', '@{', a leading '-')."""
    if run(["git", "check-ref-format", "--branch", name], repo, timeout=30)[0] != 0:
        raise Undetermined(f"cannot determine: '{name}' is not a valid branch name")


def release_facts(repo: Path, decl: dict, values: dict[str, str]) -> dict | None:
    """Everything a plan depends on, read fresh from git and the declaration — the single
    source for the printed plan, the plan id and every `--apply` step, so they cannot
    disagree. None unless both `plugin` and `version` were given (they name the release
    branch; plain `promote` works without them, exactly as before).

    The release branch's TIP is part of the facts on purpose: once it exists, an id binds
    the exact commit that would be pushed, so an approval given for one commit cannot be
    spent on another."""
    plugin, version = values.get("plugin"), values.get("version")
    if not plugin or not version:
        return None
    frm, to = decl["from"], decl["to"]
    branch = f"release/{plugin}-v{version}"
    for name in (frm, to, branch):
        _valid_branch(repo, name)
    derived = {**values, "branch": branch, "from": frm, "to": to}
    return {
        "plugin": plugin, "version": version, "branch": branch, "from": frm, "to": to,
        "from_sha": _sha(repo, f"refs/heads/{frm}"),
        "origin_from_sha": _sha(repo, f"refs/remotes/origin/{frm}"),
        "to_sha": _sha(repo, f"refs/heads/{to}"),
        "origin_to_sha": _sha(repo, f"refs/remotes/origin/{to}"),
        "branch_tip": _sha(repo, f"refs/heads/{branch}"),
        "argv": {k: fill(decl[k], derived) for k in PLAN_ARGVS if k in decl},
    }


def plan_id(facts: dict) -> str:
    """12 hex chars over the canonical facts. A STALENESS guard: any change to what the plan
    would act on changes the id. It is not authorization — anyone can compute it; the user's
    go for the exact action is the authorization."""
    blob = json.dumps(facts, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def promote(repo: Path, values: dict[str, str]) -> tuple[int, str]:
    decl = load_declaration(repo)
    tools = detected_tools(repo)
    if decl is None:
        if tools:
            return 0, (f"PROMOTE: via-tool ({', '.join(tools)} releases from CI)\n"
                       "  plan: open a PR into the release branch; the tool tags and publishes "
                       "after it merges. Nothing to run here.")
        raise Skip("nothing to promote: no .crucible/release.json and no release tool found — "
                   "declare the release path rather than have it guessed")
    via = decl.get("via", "pr")
    lines = [f"PROMOTE: {decl['from']} -> {decl['to']} via {via}"]
    lines.append(f"  1. {'open a PR' if via == 'pr' else 'merge'} {decl['from']} into {decl['to']}"
                 f"{' and wait for its checks' if via == 'pr' else ''}")
    rc = 0
    facts = release_facts(repo, decl, values)
    if "command" in decl:
        cmd = facts["argv"]["command"] if facts else fill(decl["command"], values)
        lines.append(f"  2. on {decl['to']}, on the user's explicit go for this exact action: {' '.join(cmd)}")
        lines.append("     (irreversible: confirm the tag/release from a fresh read afterwards)")
    if facts is not None:
        tip = facts["branch_tip"][:7] or "not created yet"
        lines.append(f"  release branch: {facts['branch']} (tip {tip})")
        if "prepare" in facts["argv"]:
            lines.append(f"  prepare (local, one commit): {' '.join(facts['argv']['prepare'])}")
        # Everything `--confirm` can make this script run is listed here, in full. The id proves
        # the plan has not changed; it cannot tell the user what it IS, so the plan must.
        lines.append(f"  push (external, needs --confirm): git push -u origin "
                     f"refs/heads/{facts['branch']}:refs/heads/{facts['branch']}")
        if "pr_view" in facts["argv"]:
            lines.append(f"  pr-view (read-only lookup): {' '.join(facts['argv']['pr_view'])}")
        if "open_pr" in facts["argv"]:
            lines.append(f"  open-pr (external, needs --confirm): {' '.join(facts['argv']['open_pr'])}")
        lines.append(f"  plan: {plan_id(facts)}")
    if "dry_run" in decl:
        dry = fill(decl["dry_run"], values)
        try:
            b = run_bounded(dry, repo, 600)
        except OSError as e:
            raise Undetermined(f"cannot determine: the dry run did not run ({e})") from None
        if b.killed:
            raise Undetermined(f"cannot determine: the dry run was stopped ({b.killed})")
        tail = [ln for ln in (b.stdout + b.stderr).strip().splitlines() if ln.strip()][-12:]
        lines.append(f"  dry run ({' '.join(dry)}): exit {b.returncode}")
        lines += [f"    {ln}" for ln in tail]
        rc = 0 if b.returncode == 0 else 1
    if tools:
        lines.append(f"  note: {', '.join(tools)} also configured — check which one owns releases")
    return rc, "\n".join(lines)


# --------------------------------------------------------------------------- apply: local steps
def _status(repo: Path) -> str:
    out = git_out(repo, "status", "--porcelain")
    if out is None:
        raise Undetermined("cannot determine: `git status` failed")
    return out


def _ahead(repo: Path, base_sha: str) -> int:
    n = git_out(repo, "rev-list", "--count", f"{base_sha}..HEAD")
    if n is None or not n.isdigit():
        raise Undetermined("cannot determine: could not count commits on the release branch")
    return int(n)


def _tail(text: str, n: int = 12) -> str:
    return "\n".join(f"    {ln}" for ln in [x for x in text.strip().splitlines() if x.strip()][-n:])


def step_branch(repo: Path, decl: dict, f: dict) -> tuple[int, str]:
    """Cut the release branch off `from`. Local and reversible (`git branch -D`)."""
    frm, branch = f["from"], f["branch"]
    if _status(repo):
        return 1, ("refused: the working tree is not clean. Commit or stash first — a release "
                   "branch is cut from a branch tip, and uncommitted changes would not be in it.")
    if not f["from_sha"]:
        return 1, f"refused: there is no local branch '{frm}' to cut {branch} from"
    # Best effort: judge "level with origin" against the remote as it is, not as last seen.
    # (An offline run just compares what it has.)
    run(["git", "fetch", "-q", "origin", frm], repo, timeout=60)
    origin_sha = _sha(repo, f"refs/remotes/origin/{frm}")
    if origin_sha and origin_sha != _sha(repo, f"refs/heads/{frm}"):
        return 1, (f"refused: local '{frm}' ({f['from_sha'][:7]}) is not level with origin/{frm} "
                   f"({origin_sha[:7]}). Update '{frm}' first, so the release carries exactly what "
                   "is on the remote.")
    tip = _sha(repo, f"refs/heads/{branch}")
    if tip:
        if not _contains(repo, f["from_sha"], tip):
            return 1, (f"refused: {branch} already exists but does not contain '{frm}' "
                       f"({f['from_sha'][:7]}). Inspect it; this step will not move or delete a branch.")
        return 0, f"already done: {branch} exists at {tip[:7]} and contains '{frm}' ({f['from_sha'][:7]})"
    rc, out = run(["git", "switch", "-c", branch, frm], repo, timeout=60)
    if rc != 0:
        return 1, f"`git switch -c {branch} {frm}` failed:\n{_tail(out)}"
    now = _sha(repo, "HEAD")
    if git_out(repo, "rev-parse", "--abbrev-ref", "HEAD") != branch or now != f["from_sha"]:
        raise Undetermined(f"cannot determine: {branch} was created but HEAD is not it at {frm}'s tip")
    return 0, f"created {branch} at {now[:7]} (off '{frm}'); next: --apply prepare"


def step_prepare(repo: Path, decl: dict, f: dict) -> tuple[int, str]:
    """Run the declared `prepare` argv on the release branch: it must leave exactly one new
    commit and a clean tree. Local and reversible (`git reset --hard HEAD~1`)."""
    argv = f["argv"].get("prepare")
    if not argv:
        raise Skip("nothing to prepare: .crucible/release.json declares no 'prepare' argv")
    branch = f["branch"]
    cur = git_out(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if cur != branch:
        return 1, f"refused: not on {branch} (on {cur}). Run --apply branch, then `git switch {branch}`."
    if _status(repo):
        return 1, "refused: the working tree is not clean — prepare must start from a clean branch"
    if not _contains(repo, f["from_sha"], "HEAD"):
        return 1, (f"refused: {branch} does not contain '{f['from']}' ({f['from_sha'][:7]}) — "
                   f"'{f['from']}' moved after the branch was cut. Cut the branch again (delete "
                   f"this one yourself if nothing is on it) or merge '{f['from']}' into it, so the "
                   "release commit is built on what the release will carry.")
    before = _ahead(repo, f["from_sha"])
    if before == 1:
        return 0, f"already prepared: {branch} is exactly one commit ahead of '{f['from']}'"
    if before > 1:
        return 1, (f"refused: {branch} is {before} commits ahead of '{f['from']}'; prepare expects a "
                   "branch with none (or the one release commit)")
    tip_before = _sha(repo, f"refs/heads/{branch}")
    try:
        b = run_bounded(argv, repo, 600)
    except OSError as e:
        raise Undetermined(f"cannot determine: the prepare step did not run ({e})") from None
    if b.killed:
        raise Undetermined(f"cannot determine: the prepare step was stopped ({b.killed})")
    shown = f"prepare ({' '.join(argv)})"
    if b.returncode != 0:
        return 1, f"{shown} failed with exit {b.returncode}:\n{_tail(b.stdout + b.stderr)}"
    if git_out(repo, "rev-parse", "--abbrev-ref", "HEAD") != branch or \
            _sha(repo, f"refs/heads/{branch}") == tip_before:
        return 1, (f"{shown} exited 0 but did not advance {branch} (it moved HEAD to another branch, "
                   "or committed nothing here). Inspect `git branch` and `git log` before going on.")
    after = _ahead(repo, f["from_sha"])
    if after != before + 1 or _status(repo):
        return 1, (f"{shown} exited 0 but left {after - before} new commit(s) and "
                   f"{'a dirty' if _status(repo) else 'a clean'} tree; expected exactly one commit "
                   "and a clean tree. Inspect `git log` and `git status` before going on.")
    fresh = release_facts(repo, decl, {"plugin": f["plugin"], "version": f["version"]})
    return 0, (f"prepared: one commit on {branch} ({_sha(repo, 'HEAD')[:7]})\n"
               f"  plan: {plan_id(fresh)}   <- the id for this exact commit (push / open-pr need it)")


# --------------------------------------------------------------------------- apply: external steps
# Seconds a `git push` may take before it is killed. A module constant (not a literal at the call)
# so a test can shorten it instead of waiting two minutes for a hung credential prompt.
PUSH_TIMEOUT = 120


def _remote_branch(repo: Path, branch: str) -> str:
    """The sha `origin` has for refs/heads/<branch> ('' if none) — a fresh read, never a cache."""
    rc, out = run(["git", "ls-remote", "--heads", "origin", f"refs/heads/{branch}"], repo, timeout=60)
    if rc != 0:
        raise Undetermined(f"cannot determine: could not read origin's {branch} ({_tail(out, 3).strip()})")
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) == 2 and parts[1] == f"refs/heads/{branch}":
            return parts[0]
    return ""


def step_push(repo: Path, decl: dict, f: dict) -> tuple[int, str]:
    """Push the release branch — that one ref, by explicit refspec. Never `main`, never a tag,
    never --force. External: reached only with a current --confirm."""
    branch, tip = f["branch"], f["branch_tip"]
    if not tip:
        return 1, f"refused: there is no {branch} to push. Run --apply branch, then --apply prepare."
    if _ahead(repo, f["from_sha"]) != 1 or _sha(repo, "HEAD") != tip:
        return 1, (f"refused: {branch} is not the checked-out, prepared release branch (exactly one "
                   f"commit ahead of '{f['from']}'). Run --apply prepare on it first.")
    remote = _remote_branch(repo, branch)
    if remote == tip:
        return 0, f"already pushed: origin/{branch} is at {tip[:7]}"
    if remote and not _contains(repo, remote, tip):
        return 1, (f"refused: origin/{branch} ({remote[:7]}) is not an ancestor of the local {branch} "
                   f"({tip[:7]}). This step never force-pushes; inspect the difference yourself.")
    rc, out = _run_declared(repo, ["git", "push", "-u", "origin", f"refs/heads/{branch}:refs/heads/{branch}"],
                            "`git push`", timeout=PUSH_TIMEOUT)
    if rc != 0:
        return 1, f"`git push` failed:\n{_tail(out)}"
    after = _remote_branch(repo, branch)
    if after != tip:
        raise Undetermined(f"cannot determine: pushed, but origin/{branch} reads {after[:7] or 'nothing'}, "
                           f"not {tip[:7]}")
    return 0, f"pushed {branch} at {tip[:7]} (verified from a fresh read of origin); next: --apply open-pr"


def _run_declared(repo: Path, argv: list[str], what: str, timeout: int = 120) -> tuple[int, str]:
    try:
        b = run_bounded(argv, repo, timeout)
    except OSError as e:
        raise Undetermined(f"cannot determine: {what} did not run ({e})") from None
    if b.killed:
        raise Undetermined(f"cannot determine: {what} was stopped ({b.killed})")
    return b.returncode, b.stdout + b.stderr


def _pr_exists(repo: Path, view_argv: list[str]) -> tuple[bool, str]:
    """The `pr_view` contract: exit 0 with output = a PR exists; exit 0 with NO output = none;
    any non-zero exit = could not determine. An error (auth, network) must never read as "no PR"
    and so open a duplicate — which is why "absent" is carried by empty output, not by an exit
    code (`gh pr view` uses 1 both for "none" and for failures; `gh pr list` does not)."""
    rc, out = _run_declared(repo, view_argv, "the PR lookup")
    if rc != 0:
        raise Undetermined(f"cannot determine: pr_view exited {rc}, so whether a PR exists is unknown "
                           f"(it must exit 0 and print nothing when there is none):\n{_tail(out, 4)}")
    return bool(out.strip()), out


def step_open_pr(repo: Path, decl: dict, f: dict) -> tuple[int, str]:
    """Open the release PR with the DECLARED argv — no forge is assumed here. Idempotent via the
    declared `pr_view`, and a PR it cannot read back is exit 2, never a quiet success."""
    branch, to = f["branch"], f["to"]
    manual = (f"open the PR yourself: {branch} -> {to} (a merge commit when you merge it, never a "
              "squash — a squash leaves the integration branch behind)")
    open_argv, view_argv = f["argv"].get("open_pr"), f["argv"].get("pr_view")
    if not open_argv:
        raise Skip(f"no 'open_pr' argv declared in .crucible/release.json, so no forge is assumed: {manual}")
    if not view_argv:
        raise Skip("'open_pr' is declared but 'pr_view' is not: without a way to read the PR back this "
                   f"step could be neither idempotent nor verified. Declare 'pr_view', or {manual}")
    if _remote_branch(repo, branch) != f["branch_tip"] or not f["branch_tip"]:
        return 1, f"refused: origin does not have {branch} at {f['branch_tip'][:7] or '(nothing)'} — run --apply push first"
    exists, out = _pr_exists(repo, view_argv)
    if exists:
        return 0, f"already open: a PR exists for {branch}\n{_tail(out)}"
    rc, out = _run_declared(repo, open_argv, "the PR creation")
    if rc != 0:
        return 1, f"open_pr ({' '.join(open_argv)}) failed with exit {rc}:\n{_tail(out)}"
    exists, out = _pr_exists(repo, view_argv)
    if not exists:
        raise Undetermined(f"cannot determine: open_pr exited 0 but pr_view cannot find a PR for {branch}")
    return 0, f"opened a PR for {branch} -> {to} (read back from the forge)\n{_tail(out)}\nnext: review, then merge it with a MERGE COMMIT — that is yours to do"


# Steps that act outside this checkout: they need a current plan id.
EXTERNAL_STEPS = ("push", "open-pr")
STEPS = {"branch": step_branch, "prepare": step_prepare, "push": step_push, "open-pr": step_open_pr}


def apply_step(repo: Path, step: str, values: dict[str, str], confirm: str | None) -> tuple[int, str]:
    decl = load_declaration(repo)
    if decl is None:
        raise Skip("nothing to apply: no .crucible/release.json — declare the release path "
                   "rather than have it guessed")
    facts = release_facts(repo, decl, values)
    if facts is None:
        raise Undetermined("cannot determine: --apply needs --set plugin=... and --set version=... "
                           "(together they name the release branch)")
    if step in EXTERNAL_STEPS:
        # Checked BEFORE anything runs, so a refusal cannot have side effects.
        if not confirm:
            raise Undetermined(
                f"cannot determine: '{step}' acts outside this checkout, so it needs --confirm <plan id> "
                "from `promote` — and the user's explicit go for this exact action; the id only "
                "proves the plan has not changed since it was shown")
        now = plan_id(facts)
        if confirm != now:
            raise Stale(f"STALE PLAN: --confirm {confirm} is not the current plan ({now}). "
                        "Something it acts on has changed since it was shown; run `promote` again, "
                        "show the user the new plan, and ask again.")
    return STEPS[step](repo, decl, facts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("recommend")
    r.add_argument("--target")
    r.add_argument("--offline", action="store_true", help="do not ask the remote about protection")
    pr = sub.add_parser("promote")
    pr.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    pr.add_argument("--apply", choices=["branch", "prepare", "push", "open-pr"],
                    help="run one step of the declared release route (see the module docstring)")
    pr.add_argument("--confirm", metavar="PLAN_ID",
                    help="the `plan:` id from `promote`; required for push and open-pr")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    try:
        if git_out(repo, "rev-parse", "--git-dir") is None:
            raise Undetermined(f"cannot determine: {repo} is not a git repository")
        if a.cmd == "recommend":
            print(recommend(repo, a.target, not a.offline))
            return 0
        if a.cmd == "promote":
            values = dict(item.split("=", 1) for item in a.set if "=" in item)
            if a.apply:
                code, text = apply_step(repo, a.apply, values, a.confirm)
                print(text)
                return code
            code, text = promote(repo, values)
            print(text)
            return code
        raise Undetermined("cannot determine: pass recommend or promote")
    except Undetermined as e:
        print(str(e), file=sys.stderr)
        return 2
    except Stale as e:
        print(str(e), file=sys.stderr)
        return 4
    except Skip as e:
        print(f"{e}\nThis is a SKIP, not a pass.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    utf8_stdio()
    raise SystemExit(main())
