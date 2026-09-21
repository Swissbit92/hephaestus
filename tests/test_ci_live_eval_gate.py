"""The three states of `live-eval`, pinned so they cannot collapse into each other.

`live-eval` spends tokens and drives the real `claude` CLI, so it is off by default. Being
off is a *third* state, and the whole point of this file is that it stays distinguishable
from the other two:

    flag off                 -> SKIPPED. Not configured, and reported as not configured.
    flag on, secret missing  -> FAILS (exit 2). A real misconfiguration.
    flag on, secret present  -> runs, and its own result stands.

Both ways of collapsing that have already happened here, which is why these are tests and
not a comment:

- **Off was reported as failing.** The cron was switched on in `e8bd821` while the
  ANTHROPIC_API_KEY secret was never added, so the job failed 6 of 6 scheduled runs and had
  never once passed. A gate that has only ever been red gets skimmed past, and then its true
  alarms get skimmed past too.
- **The obvious fix would have collapsed it the other way.** Turning the `exit 2` into an
  `exit 0` makes the run green while nothing has been verified, which is the one thing this
  repo refuses everywhere else. `test_missing_key_still_fails_loudly` exists to make that
  edit fail CI rather than pass it.

Stdlib only, deliberately: `pyyaml` is not a dependency of this repo and CI installs only
pytest, so importing it would turn this file into a collection error — taking the entire
suite down to check one workflow.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _ci_text() -> str:
    return CI_YML.read_text(encoding="utf-8")


def _job_block(name: str, text: str) -> str:
    """The lines of one job, from `  <name>:` to the next job at the same indent."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"  {name}:"))
    for end in range(start + 1, len(lines)):
        ln = lines[end]
        if re.match(r"^  [A-Za-z0-9_-]+:", ln):
            return "\n".join(lines[start:end])
    return "\n".join(lines[start:])


# ------------------------------------------------------------------- the file itself
def test_ci_workflow_exists():
    assert CI_YML.is_file(), f"expected a workflow at {CI_YML}"


# ------------------------------------------------------------------------- flag gating
def test_live_eval_is_gated_on_the_enable_flag():
    """Off must mean *skipped*, which requires the flag in the job-level `if:`.

    `vars` and not `secrets`: the secrets context is not available in a job-level `if:`
    (only github/needs/vars/inputs are), so key presence cannot be tested there at all.
    """
    block = _job_block("live-eval", _ci_text())
    assert "vars.LIVE_EVAL_ENABLED" in block, (
        "live-eval is not gated on vars.LIVE_EVAL_ENABLED — with the flag absent from the "
        "`if:`, an unconfigured suite runs and fails every week instead of being skipped"
    )


def test_live_eval_still_only_runs_on_dispatch_or_schedule():
    """The flag is an *additional* gate, not a replacement for the trigger gate.

    Without this, adding the flag could quietly widen the job to every push and PR — the
    token-spending shape the `if: false` originally existed to prevent.
    """
    block = _job_block("live-eval", _ci_text())
    assert "workflow_dispatch" in block and "schedule" in block, (
        "live-eval lost its trigger gate; it must still run only on dispatch or schedule"
    )
    assert "github.event_name" in block


# ------------------------------------------------------- the guard that must stay loud
def test_missing_key_still_fails_loudly():
    """`exit 2` stays. A configured-on job with no key is a misconfiguration, not a pass.

    This is the regression guard for the tempting fix: making the weekly red go away by
    exiting 0. That paints "nothing was verified" as "verified", which is the failure this
    repo refuses everywhere else.
    """
    block = _job_block("live-eval", _ci_text())
    assert "exit 2" in block, (
        "the missing-key guard no longer exits 2 — an unconfigured live suite would report "
        "as passing"
    )
    # Deliberately coarse: a substring search over the whole job block, so an unrelated
    # future step containing the literal "exit 0" would trip it. That direction is the safe
    # one — a spurious red costs a comment, a spurious green costs the guard.
    assert "exit 0" not in block, (
        "the missing-key guard appears to exit 0; 'not configured' must not look like 'passing'"
    )


# ----------------------------------------------------------------------------- the cron
def test_weekly_cron_avoids_the_top_of_the_hour():
    """GitHub names :00 a high-load window and drops queued runs under load.

    A dropped run leaves no record at all, so a missing weekly check is indistinguishable
    from one that has not fired yet. Measured here before the move: the first two runs fired
    ~35 min late, the next four 5-6 hours late.
    """
    crons = re.findall(r'cron:\s*"([^"]+)"', _ci_text())
    assert crons, "no cron schedule found in the workflow"
    for expr in crons:
        minute = expr.split()[0]
        assert minute != "0", (
            f'cron "{expr}" fires at the top of the hour, which GitHub documents as a '
            f"high-load window; pick another minute"
        )
