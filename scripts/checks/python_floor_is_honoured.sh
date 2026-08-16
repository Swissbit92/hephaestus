#!/bin/sh
# Every shipped .py must parse on the interpreter the README promises.
#
# This is the static half. It runs anywhere, including on a machine that only has a new
# Python, which is the case that let the original defect through: the author's interpreter
# accepted PEP 701 f-string syntax, CI pinned a single 3.12, and the suite was uncollectable
# on 3.9/3.10/3.11 for everyone else.
#
# The dynamic half is CI's python-version matrix, which is the only thing that can prove a
# real interpreter loads the tree. Neither substitutes for the other.
. "$(dirname "$0")/_python.sh"
exec "$PY" "$(dirname "$0")/../python_floor.py" --repo "$(dirname "$0")/../.."
