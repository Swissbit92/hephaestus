#!/usr/bin/env python3
"""The per-milestone fix budget for develop — rounds, setup failures, repeats, time.

develop's QA loop used to be "REJECT → fix, re-run QA; do not proceed until PASS": no cap,
no stop condition. In practice that produced a milestone that ran about seven rounds and
ten agent-hours past its budget, and the same-failure-twice rule meant to catch it never
fired, because every round failed for a *different* reason and so looked like progress.
The literature says the same from the other side: once a recovery runs past the length of
a typical successful one, further repair rarely helps.

So the budget counts every failed round, whatever its cause:

  - **fix rounds** — every REJECT, any kind. Default cap 3 per milestone.
  - **setup rounds** — failures of the environment rather than the change (kind `setup`),
    counted separately so a broken toolchain cannot spend the fix budget. Default cap 3.
  - **repeats** — the same kind failing twice since the last diagnosis means stop and find
    the mechanism before another attempt; a third variation of the same idea is a sweep.
  - **time** — 2x the milestone's estimate, from when it started (or was last extended).

At a cap the answer is a checkpoint with the user — ship the best result, continue for
another budget, or restart the milestone from the plan — never a decision the agent makes
for itself. `extend`, `restart`, `ship` and `init` therefore require `--user-said`, the
user's words, which go into the ledger and are printed by `report`. That makes a cap change
VISIBLE, not impossible: this is bookkeeping an agent runs, not a lock against it.

For FULL work a PASS does not close a milestone until its research is recorded. A prose
"research each milestone" step gets skipped; a gate that names the missing step is loud.

Storage: ``<git-dir>/crucible/ledger-<branch>.jsonl`` — append-only JSON lines in the
repo's git directory, keyed by branch. Never committed, never merged, and per worktree (a
linked worktree has its own git dir). Caps and counters are derived from the event log on
every call, so there is no second copy of the state to drift.

Usage:
  milestone_ledger.py init --tier FULL --estimate M1=45 --estimate M2=30 --user-said "..."
  milestone_ledger.py start M1
  milestone_ledger.py research M1 --note "what was looked up, and what it changed"
  milestone_ledger.py record M1 --verdict REJECT --kind tests     # writes, then evaluates
  milestone_ledger.py status M1                                   # evaluates only
  milestone_ledger.py diagnose M1 --note "the mechanism"
  milestone_ledger.py extend|restart|ship M1 --user-said "..."
  ULTRA (opt-in, the user's words must say so):
  milestone_ledger.py init --tier ULTRA --checkpoint M2 [--criteria acceptance.json] --user-said "..."
  milestone_ledger.py decide M1 --note "a choice made without asking, and why"
  milestone_ledger.py clear M2 --user-said "..."                   # lift a pre-registered stop
  milestone_ledger.py report

The first stdout line of record/status is machine-readable: ``PROCEED``, ``DONE`` or
``STOP <REASON>`` with REASON one of CHECKPOINT-ROUNDS, CHECKPOINT-SETUP, CHECKPOINT-TIME,
DIAGNOSE, RESEARCH-MISSING, CHECKPOINT-PREREGISTERED.

Exit codes:
  0 — proceed (or the milestone is done)
  1 — STOP: the reason is on the first line; do not attempt another fix
  2 — could not determine: no ledger, detached HEAD, unknown milestone, unreadable ledger,
      or a refused write (empty note, missing --user-said). NOT a pass.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crucible_common import current_branch, git_out, utf8_stdio  # noqa: E402

DEFAULT_FIX_CAP = 3
DEFAULT_SETUP_CAP = 3
SAME_KIND_LIMIT = 2
TIME_FACTOR = 2
SCHEMA = 1

TIERS = ("FULL", "LIGHT", "TRIVIAL", "ULTRA")
RESEARCH_TIERS = ("FULL", "ULTRA")
# ULTRA is opt-in only: never a tier the agent picks for itself. The guard is the user's own
# words, which must name it — as strong as the cap guard, and as honest about its limit (the
# agent writes the quote). Phase 0's confirmation is the real gate.
_ULTRA_WORD = re.compile(r"\bultra\b", re.I)
VERDICTS = ("PASS", "CONDITIONAL_PASS", "REJECT")
# One per gate that can fail a round, so "the same kind twice" means the same gate twice.
# `setup` is the environment, not the change, and goes to its own budget.
KINDS = ("tests", "coverage", "lint", "clones", "revert", "mutation", "invariant",
         "review", "security", "perf", "other", "setup")
PASSING = ("PASS", "CONDITIONAL_PASS")


class Undetermined(Exception):
    """Raised for anything that should exit 2."""


# --------------------------------------------------------------------------- storage
def ledger_path(repo: Path) -> Path:
    git_dir = git_out(repo, "rev-parse", "--absolute-git-dir")
    if not git_dir:
        raise Undetermined(f"cannot determine the ledger: {repo} is not a git repository")
    branch = current_branch(repo)
    if not branch:
        raise Undetermined("cannot determine the ledger: HEAD is detached, so there is no "
                           "branch to key it to")
    return Path(git_dir) / "crucible" / f"ledger-{quote(branch, safe='')}.jsonl"


def load(path: Path) -> list[dict]:
    if not path.exists():
        raise Undetermined(f"cannot determine: no milestone ledger at {path.as_posix()} — "
                           "run `init` at plan approval")
    events = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            raise Undetermined(f"cannot determine: ledger line {n} is not JSON") from None
        if not isinstance(ev, dict) or "event" not in ev:
            raise Undetermined(f"cannot determine: ledger line {n} has no event")
        events.append(ev)
    if not events or events[0].get("event") != "init":
        raise Undetermined("cannot determine: the ledger does not start with an init event")
    return events


def append(path: Path, event: dict, now: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"v": SCHEMA, "at": now, **event}, sort_keys=True) + "\n")


def parse_at(s: str) -> _dt.datetime:
    return _dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc)


def fmt_at(t: _dt.datetime) -> str:
    return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- evaluation
def milestone_state(events: list[dict], m: str) -> dict:
    """Fold the log into one milestone's budget. Pure, so it is tested without git."""
    init = events[0]
    fix_cap = int(init.get("fix_cap", DEFAULT_FIX_CAP))
    setup_cap = int(init.get("setup_cap", DEFAULT_SETUP_CAP))
    st = {"milestone": m, "tier": init.get("tier", "FULL"), "started": False, "window_at": None,
          "base_fix_cap": fix_cap, "fix_cap": fix_cap, "setup_cap": setup_cap,
          "rounds": 0, "setup": 0,
          "since_diagnose": [], "research": False, "passed": False, "shipped": False,
          "extensions": 0, "restarts": 0, "cleared": False,
          "checkpoint": m in (init.get("checkpoints") or []),
          "estimate": (init.get("estimates") or {}).get(m)}
    for ev in events[1:]:
        if ev.get("milestone") != m:
            continue
        kind = ev["event"]
        if kind == "start" and not st["started"]:
            st["started"], st["window_at"] = True, ev.get("at")
        elif kind == "research":
            st["research"] = True
        elif kind == "diagnose":
            st["since_diagnose"] = []
        elif kind == "verdict":
            if ev.get("verdict") in PASSING:
                st["passed"] = True
            elif ev.get("verdict") == "REJECT":
                # a REJECT after a pass reopens the milestone: a regression found in final
                # verification must count against the budget, not slip past a sticky PASS
                st["passed"] = False
                if ev.get("kind") == "setup":
                    st["setup"] += 1
                else:
                    st["rounds"] += 1
                    st["since_diagnose"].append(ev.get("kind", "other"))
        elif kind == "extend":
            st["extensions"] += 1
            st["fix_cap"] += fix_cap
            st["setup_cap"] += setup_cap
            st["window_at"] = ev.get("at")
        elif kind == "restart":
            st["restarts"] += 1
            st.update(rounds=0, setup=0, since_diagnose=[], passed=False,
                      fix_cap=fix_cap, setup_cap=setup_cap, window_at=ev.get("at"))
        elif kind == "ship":
            st["shipped"] = True
        elif kind == "clear":
            st["cleared"] = True
    return st


def pending_checkpoint(events: list[dict]) -> str | None:
    """The first milestone that passed QA, carries a pre-registered checkpoint, and has not
    been cleared by the user — the run must stop there before anything else starts."""
    for m in (events[0].get("checkpoints") or []):
        st = milestone_state(events, m)
        if (st["passed"] or st["shipped"]) and not st["cleared"]:
            return m
    return None


def criteria_digest(path: Path) -> str:
    """Hash of the acceptance criteria with every `pass` flag removed: the run may flip a
    criterion to passing, never rewrite, add or delete one."""
    def strip(x):
        if isinstance(x, dict):
            return {k: strip(v) for k, v in sorted(x.items()) if k != "pass"}
        if isinstance(x, list):
            return [strip(v) for v in x]
        return x
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Undetermined(f"cannot determine: acceptance criteria {path.as_posix()} unreadable ({e})") from None
    return hashlib.sha256(json.dumps(strip(data), sort_keys=True).encode()).hexdigest()


def check_criteria(repo: Path, init: dict) -> None:
    ref = init.get("criteria")
    if not ref:
        return
    if criteria_digest(Path(repo) / ref["path"]) != ref["sha256"]:
        raise Undetermined(f"refused: the acceptance criteria in {ref['path']} changed after the run "
                           "started (beyond pass flags) — log it with `decide`, then re-init with "
                           "--replace and the user's words")


def evaluate(st: dict, now: _dt.datetime) -> tuple[int, str, str]:
    """(exit code, machine line, human line). Checkpoints outrank DIAGNOSE: once the budget
    is spent, the question is whether to keep going at all, not how to make the next try."""
    m = st["milestone"]
    if st["shipped"]:
        return 0, "DONE", f"{m}: shipped at a checkpoint on the user's word"
    if st["passed"]:
        if st["tier"] in RESEARCH_TIERS and not st["research"]:
            return 1, "STOP RESEARCH-MISSING", (
                f"{m} passed QA but has no research recorded — a {st['tier']} milestone starts "
                f"with its own research; record it with `research {m} --note ...`")
        if st["checkpoint"] and not st["cleared"]:
            return 1, "STOP CHECKPOINT-PREREGISTERED", (
                f"{m} passed — the user registered a checkpoint here before the run. Stop and "
                f"ask them how to go on; record their answer with `clear {m} --user-said ...`")
        return 0, "DONE", f"{m}: passed"
    minutes = None
    if st["window_at"] and st["estimate"]:
        minutes = (now - parse_at(st["window_at"])).total_seconds() / 60
    budget = (f"{m}: fix round {st['rounds']}/{st['fix_cap']} · setup "
              f"{st['setup']}/{st['setup_cap']}")
    if minutes is not None:
        budget += f" · {minutes:.0f}/{st['estimate'] * TIME_FACTOR} min"
    if st["rounds"] >= st["fix_cap"]:
        return 1, "STOP CHECKPOINT-ROUNDS", f"{budget} — fix budget spent. Ask the user: " \
            f"ship the best result, continue (+{st['base_fix_cap']} rounds), " \
            "or restart the milestone from the plan"
    if st["setup"] >= st["setup_cap"]:
        return 1, "STOP CHECKPOINT-SETUP", f"{budget} — the environment keeps failing, not " \
            "the change. Ask the user: ship, continue, or restart"
    if minutes is not None and minutes > st["estimate"] * TIME_FACTOR:
        return 1, "STOP CHECKPOINT-TIME", f"{budget} — over twice the estimate. Ask the " \
            "user: ship the best result, continue, or restart from the plan"
    repeats = [k for k in set(st["since_diagnose"]) if st["since_diagnose"].count(k) >= SAME_KIND_LIMIT]
    if repeats:
        return 1, "STOP DIAGNOSE", f"{budget} — '{sorted(repeats)[0]}' failed twice. Find the " \
            f"mechanism before another attempt, then `diagnose {m} --note ...`"
    return 0, "PROCEED", budget


# --------------------------------------------------------------------------- CLI
def _parse_estimates(items: list[str]) -> dict[str, int]:
    out = {}
    for item in items or []:
        name, _, minutes = item.partition("=")
        if not name or not minutes.isdigit() or int(minutes) <= 0:
            raise Undetermined(f"cannot determine: --estimate wants M=minutes, got {item!r}")
        out[name] = int(minutes)
    return out


def _need(value: str | None, what: str) -> str:
    # Checked by hand, not argparse `required=True`: argparse's own exit 2 would answer
    # first, and the reason the value is required would never be printed.
    if not value or not value.strip():
        raise Undetermined(f"refused: {what}")
    return value.strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=".")
    ap.add_argument("--now", help=argparse.SUPPRESS)  # tests pin the clock
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("init")
    p.add_argument("--tier", default="FULL", choices=TIERS)
    p.add_argument("--estimate", action="append", default=[])
    p.add_argument("--fix-cap", type=int, default=DEFAULT_FIX_CAP)
    p.add_argument("--setup-cap", type=int, default=DEFAULT_SETUP_CAP)
    p.add_argument("--user-said")
    p.add_argument("--replace", action="store_true")
    p.add_argument("--checkpoint", action="append", default=[], metavar="M",
                   help="ULTRA: stop after milestone M passes (repeatable)")
    p.add_argument("--criteria", help="ULTRA: acceptance-criteria JSON frozen for the run")
    for name in ("start", "status"):
        sub.add_parser(name).add_argument("milestone")
    for name in ("research", "diagnose", "decide"):
        p = sub.add_parser(name)
        p.add_argument("milestone")
        p.add_argument("--note")
    p = sub.add_parser("record")
    p.add_argument("milestone")
    p.add_argument("--verdict", choices=VERDICTS)
    p.add_argument("--kind", choices=KINDS, default="other")
    for name in ("extend", "restart", "ship", "clear"):
        p = sub.add_parser(name)
        p.add_argument("milestone")
        p.add_argument("--user-said")
    sub.add_parser("report")

    a = ap.parse_args(argv)
    repo = Path(a.repo)
    try:
        if not a.cmd:
            raise Undetermined("cannot determine: no subcommand (see --help)")
        now_dt = parse_at(a.now) if a.now else _dt.datetime.now(_dt.timezone.utc)
        now = fmt_at(now_dt)
        path = ledger_path(repo)

        if a.cmd == "init":
            said = _need(a.user_said, "init needs --user-said: caps are the user's to set")
            if path.exists() and not a.replace:
                raise Undetermined("refused: a ledger already exists for this branch; "
                                   "re-init only with --replace and the user's words")
            if a.fix_cap < 1 or a.setup_cap < 1:
                raise Undetermined("refused: caps must be at least 1")
            estimates = _parse_estimates(a.estimate)
            extra = {}
            if a.tier == "ULTRA":
                if not _ULTRA_WORD.search(said):
                    raise Undetermined("refused: ULTRA is opt-in — the user's own words must ask "
                                       "for it (--user-said must contain ULTRA)")
                extra["checkpoints"] = a.checkpoint
                if a.criteria:
                    extra["criteria"] = {"path": Path(a.criteria).as_posix(),
                                         "sha256": criteria_digest(Path(repo) / a.criteria)}
            elif a.checkpoint or a.criteria:
                raise Undetermined("refused: --checkpoint and --criteria belong to an ULTRA run")
            if path.exists():
                path.unlink()
            append(path, {"event": "init", "tier": a.tier, "fix_cap": a.fix_cap,
                          "setup_cap": a.setup_cap, "estimates": estimates,
                          "user_said": said, **extra}, now)
            print(f"ledger ready: {path.as_posix()} · fix cap {a.fix_cap} · setup cap "
                  f"{a.setup_cap} · {len(estimates)} estimate(s)")
            return 0

        events = load(path)
        if a.cmd == "report":
            names = list((events[0].get("estimates") or {}).keys())
            for e in events[1:]:      # each milestone once, in order of first appearance
                if e.get("milestone") and e["milestone"] not in names:
                    names.append(e["milestone"])
            for m in names:
                _, line, human = evaluate(milestone_state(events, m), now_dt)
                print(f"{line:<24} {human}")
            for e in events:
                if e["event"] == "decide":
                    print(f"decided alone ({e.get('milestone')}): {e.get('note')}")
            for e in events:
                if e.get("user_said"):
                    print(f"user said ({e['event']}{' ' + e['milestone'] if e.get('milestone') else ''}): "
                          f"{e['user_said']}")
            return 0

        m = a.milestone
        st = milestone_state(events, m)
        if a.cmd == "start":
            held = pending_checkpoint(events)
            if held and held != m:
                print("STOP CHECKPOINT-PREREGISTERED")
                print(f"{held} passed and the user registered a checkpoint there — ask them "
                      f"before starting {m}; record the answer with `clear {held} --user-said ...`")
                return 1
            if not st["started"]:
                append(path, {"event": "start", "milestone": m}, now)
            print(f"{m} started")
            return 0
        if not st["started"]:
            raise Undetermined(f"cannot determine: milestone {m} was never started")
        if a.cmd in ("research", "diagnose", "decide"):
            note = _need(a.note, f"{a.cmd} needs a non-empty --note")
            append(path, {"event": a.cmd, "milestone": m, "note": note}, now)
            st = milestone_state(load(path), m)
        elif a.cmd in ("extend", "restart", "ship", "clear"):
            said = _need(a.user_said, f"{a.cmd} needs --user-said: only the user changes a cap")
            if a.cmd == "ship":
                check_criteria(repo, events[0])
            append(path, {"event": a.cmd, "milestone": m, "user_said": said}, now)
            st = milestone_state(load(path), m)
        elif a.cmd == "record":
            verdict = _need(a.verdict, "record needs --verdict PASS|CONDITIONAL_PASS|REJECT")
            if verdict in PASSING:
                check_criteria(repo, events[0])
            append(path, {"event": "verdict", "milestone": m, "verdict": verdict,
                          "kind": a.kind}, now)
            st = milestone_state(load(path), m)

        code, line, human = evaluate(st, now_dt)
        print(line)
        print(human)
        return code
    except Undetermined as e:
        print(str(e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    utf8_stdio()
    raise SystemExit(main())
