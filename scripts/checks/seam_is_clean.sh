#!/bin/sh
# Fails when a generic plugin carries a domain token. See docs/INVARIANTS.md.
. "$(dirname "$0")/_python.sh"
run_pytest tests/test_seam.py -q -o addopts=
exit $?
