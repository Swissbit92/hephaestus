#!/bin/sh
# Every Phase 4.0 script must exit with a code distinct from success when it cannot
# complete its check. These tests assert exactly that, one per script.
. "$(dirname "$0")/_python.sh"
run_pytest -q -o addopts= \
  tests/test_coverage_delta.py::test_exit_2_when_it_cannot_tell \
  tests/test_coverage_delta.py::test_zero_vs_zero_is_not_a_pass \
  tests/test_detect_profile.py::test_exit_2_on_malformed_manifest \
  tests/test_detect_profile.py::test_exit_3_when_no_markers_and_it_says_so \
  tests/test_invariants_run.py::test_exit_2_when_the_check_path_is_missing \
  tests/test_invariants_run.py::test_exit_3_when_stated_but_never_wired \
  tests/test_milestone_ledger.py::test_exit_2_when_there_is_no_ledger \
  tests/test_milestone_ledger.py::test_exit_2_on_detached_head \
  tests/test_milestone_ledger.py::test_exit_2_for_an_unreadable_ledger \
  tests/test_qa_gates.py::test_a_malformed_parallel_declaration_is_undetermined \
  tests/test_qa_gates.py::test_aggregate_never_folds_could_not_determine_into_a_pass \
  tests/test_integrate.py::test_a_malformed_declaration_is_undetermined \
  tests/test_integrate.py::test_an_undeclared_repo_is_a_skip_not_a_guess
exit $?
