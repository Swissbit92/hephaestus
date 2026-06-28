"""hephaestus skill-eval harness.

Measures whether the plugins behave as their SKILL.md specifies. Deterministic-first:
assert on git/file world-state and tool-call traces; an optional pinned-Claude rubric
judge covers only the few qualitative criteria. The pure modules (model, scoring,
reliability, report, judge prompt/parse) import with no third-party dependency and are
unit-tested headless; the live runner (runner.py, world.py) drives the `claude` CLI / Agent
SDK and is skipped when neither is available.
"""
