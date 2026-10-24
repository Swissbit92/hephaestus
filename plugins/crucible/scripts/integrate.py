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

Exit codes: 0 advice/plan printed (and the dry run passed) · 1 the declared dry run failed ·
2 could not determine (no target, malformed declaration, missing placeholder) · 3 nothing
declared or detected (promote) — a SKIP.
"""
from __future__ import annotations

import argparse
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
    for key in ("command", "dry_run"):
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
    if "command" in decl:
        cmd = fill(decl["command"], values)
        lines.append(f"  2. on {decl['to']}, on the user's explicit go for this exact action: {' '.join(cmd)}")
        lines.append("     (irreversible: confirm the tag/release from a fresh read afterwards)")
    if "dry_run" in decl:
        dry = fill(decl["dry_run"], values)
        try:
            p = subprocess.run(dry, cwd=str(repo), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=600)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise Undetermined(f"cannot determine: the dry run did not run ({e})") from None
        tail = [ln for ln in (p.stdout + p.stderr).strip().splitlines() if ln.strip()][-12:]
        lines.append(f"  dry run ({' '.join(dry)}): exit {p.returncode}")
        lines += [f"    {ln}" for ln in tail]
        rc = 0 if p.returncode == 0 else 1
    if tools:
        lines.append(f"  note: {', '.join(tools)} also configured — check which one owns releases")
    return rc, "\n".join(lines)


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
            code, text = promote(repo, values)
            print(text)
            return code
        raise Undetermined("cannot determine: pass recommend or promote")
    except Undetermined as e:
        print(str(e), file=sys.stderr)
        return 2
    except Skip as e:
        print(f"{e}\nThis is a SKIP, not a pass.", file=sys.stderr)
        return 3


if __name__ == "__main__":
    utf8_stdio()
    raise SystemExit(main())
