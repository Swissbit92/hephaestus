#!/bin/sh
# Every Phase 4.0 script must exit with a code distinct from success when it cannot
# complete its check. These tests assert exactly that, one per script.
. "$(dirname "$0")/_python.sh"
exec "$PY" -m pytest -q -o addopts= \
  tests/test_coverage_delta.py::test_exit_2_when_it_cannot_tell \
  tests/test_coverage_delta.py::test_zero_vs_zero_is_not_a_pass \
  tests/test_detect_profile.py::test_exit_2_on_malformed_manifest \
  tests/test_detect_profile.py::test_exit_3_when_no_markers_and_it_says_so \
  tests/test_invariants_run.py::test_exit_2_when_the_check_path_is_missing \
  tests/test_invariants_run.py::test_exit_3_when_stated_but_never_wired
