#!/bin/sh
# Fails when shipped plugin code decides anything from a file's mtime. See docs/INVARIANTS.md.
#
# git does not restore modification times, so a clone stamps every file with the checkout
# time. This repo learned that in render.py, wrote it down only in render.py's docstring,
# and then shipped the identical bug at four more sites — one of which persisted a wrong
# date into a file. That is the gap a check closes and a comment does not.
. "$(dirname "$0")/_python.sh"
exec "$PY" "$(dirname "$0")/../mtime_guard.py" --repo "$(dirname "$0")/../.."
