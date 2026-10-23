#!/bin/sh
# Sets $PY to a Python interpreter that actually runs. Source it; do not execute it.
#
# `command -v python3` is not evidence on Windows: the name normally resolves to the
# Microsoft Store App Execution Alias, which prints an install ad, runs nothing and
# exits 49. A check wired to that name fails for a reason unrelated to what it checks —
# which is how the "a check that could not run is never a pass" invariant came to fail
# by being unable to run.
#
# So probe by execution, not by resolution. Honour $PYTHON first for an explicit override.

if [ -n "${PYTHON:-}" ] && "$PYTHON" -c "" >/dev/null 2>&1; then
  PY="$PYTHON"
else
  PY=""
  for _candidate in python3 python py; do
    if command -v "$_candidate" >/dev/null 2>&1 && "$_candidate" -c "" >/dev/null 2>&1; then
      PY="$_candidate"
      break
    fi
  done
fi

if [ -z "$PY" ]; then
  echo "no working python interpreter found (tried \$PYTHON, python3, python, py)" >&2
  # 2, not 1: this is "could not determine", which must never read as a passing check.
  exit 2
fi

# Runs pytest with $PY, keeping "could not run" apart from "failed".
#
# `python -m pytest` with no pytest installed exits 1 — the same code as a failing test —
# so a check run on a machine without pytest reported the invariant VIOLATED. pytest's own
# codes 2-5 (interrupted, internal error, usage error, nothing collected) are not evidence
# either way. All of those become 2, the "could not determine" every check here uses.
run_pytest() {
  if ! "$PY" -c "import pytest" >/dev/null 2>&1; then
    echo "cannot determine: pytest is not installed for $PY (set \$PYTHON to an interpreter that has it)" >&2
    return 2
  fi
  "$PY" -m pytest "$@"
  _rc=$?
  if [ "$_rc" -ge 2 ] && [ "$_rc" -le 5 ]; then
    echo "cannot determine: pytest exited $_rc (interrupted, internal error, usage error or nothing collected)" >&2
    return 2
  fi
  return "$_rc"
}
