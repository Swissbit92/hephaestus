# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **crucible 0.5.0 — `flag-gate` skill.** Default-OFF feature-flag rollout with instant revert (legacy path byte-identical, flip on an eval-first gate, revert by flipping off, retire after soak). Pure methodology skill; pairs with `eval-first`.
- **crucible 0.4.0 — `eval-first` skill.** Eval-first methodology + generic stdlib scripts (`ab_harness`, `baseline`, `judge`, `deterministic`, `reliability`) and scaffolding templates. Freeze an immutable baseline → deterministic-first checks → swap-augmented blind A/B judge (pinned, self-grading-guarded) → match-or-beat-or-revert verdict. 38 tests.

### Changed
-

### Fixed
- **crucible 0.5.1 — qa-gatekeeper live baseline.** The QA gate re-derives the test baseline from ground truth (the branch-point commit via `git merge-base`, counted in a throwaway worktree) instead of trusting a stated count, and treats only a *drop* in passing tests or a new failure as a regression (added tests are expected, not a regression). Kills the stale-baseline false-alarm → loop-trustworthy gate. Aligned `develop` + `start-branch` baseline wording to match.

## [0.1.0] — 2026-06-28

### Added
- Initial repository scaffolding via `/cms init`.
