# Evidence profiles — what each marker implies

Loaded only when extending or debugging `scripts/detect_profile.py`. `develop.md` Phase 4.0
carries the two-line summary; everything that would bloat it lives here.

## Why detection rather than one gate

A workflow with one hardcoded check is wrong in both directions: it runs commands a project
does not have, and misses the ones it does. Two failures follow, and the second is worse:

- **Ungated subtrees.** A repo often holds more than one project — a frontend inside a
  backend, or a sibling service with its own dependencies and tests. A detector that stops at
  the repository root reports "checks passed" while whole subtrees were never examined.
- **Vacuous green.** A gate pointed at nothing exits successfully. Zero tests collected is
  not zero tests failing, and a check that could not run must never be recorded as a check
  that passed.

## The three states

| State | Meaning | What Phase 4.0 does |
|---|---|---|
| **gate** | Runnable now, hermetic, deterministic | Run it; the exit code is the evidence |
| **capability** | Present, but needs a live service or browser | Report it; never gate on it |
| **absent** | No marker | Skip — and say "skip", never "pass" |

`--emit-gates` is what makes the split load-bearing rather than decorative: it prints only
the gates, one runnable command per line, already scoped to the right directory. A
capability is never printed there — it goes to stderr — so it cannot be run by accident
against a service that is not up.

`capability` exists because "installed" and "wired" are different facts. A browser suite whose
config names a base URL but starts no server assumes something is already listening; run it in
CI and it collects nothing and exits clean. That is the vacuous green above, wearing a
convincing costume.

## Exit codes

`0` roots found · `2` could not determine · `3` no markers (skip). `1` is deliberately unused —
a detector has no "regression" concept, and leaving the code free stops it being read as one
by analogy with its sibling scripts.

Every Phase 4.0 script shares this shape: **a distinct code for "I could not tell", never
folded into success.** A check that cannot run is not a check that passed.

## Marker → gate rules

### Python

A project root is any directory with a `pyproject.toml`, a pytest configuration, or a
`tests/` directory alongside a `requirements.txt`.

Pytest configuration lives in **four** places and file existence answers the wrong question —
a `pyproject.toml` may configure only the linter:

| Where | Detected by |
|---|---|
| `pyproject.toml` | contains `[tool.pytest.ini_options]` |
| `pytest.ini` | file exists |
| `setup.cfg` | contains `[tool:pytest]` |
| `tox.ini` | contains `[pytest]` |

Gates: `pytest`, `coverage_delta.py --repo <root>`, plus `ruff check` / `ruff format --check`
when a ruff config is present, `mypy` when configured, and `pre-commit run --all-files` when
that config exists (its hook list may extend well beyond the linter already found — check it
rather than assuming it duplicates).

Coverage thresholds are **read and reported, never imposed**. They differ per project and
already live inside the project's own test command; re-asserting one from the outside would
invent a requirement the project never made.

### Node

A project root is any directory with a `package.json`.

**Read both dependency maps.** Some scaffolds place `typescript`, `eslint`, `jest` and the
testing libraries in `dependencies` rather than `devDependencies`; keying on devDependencies
alone reports a fully-tooled application as having nothing to run.

**A declared script beats a guessed command.** If `scripts.lint` exists, run `npm run lint` —
the project may lint with something other than the tool its dependencies suggest.

Gates: `npm run build` (which typechecks when the toolchain wires that in — if it does not,
add `tsc --noEmit`), lint, tests. Browser suites are gated only when their config starts a
server; otherwise they are a capability.

The hard gate here is structurally identical to the Python one — build, typecheck, lint, test.
Published frontend workflows converge on that and treat screenshots, visual diffing and
accessibility sweeps as advisory: near-universal in existence, mandatory in almost none. A
model scoring its own rendered output is a weak judge of it, so visual output belongs in the
evidence a human reads, not in a pass/fail gate.

## Deliberate non-goals

- **No rules for ecosystems with no evidence behind them.** The marker set was derived from a
  survey of real repositories. Toolchains absent from that survey get no rules, because a
  guessed command that fails confusingly is worse than an honest "no marker found". Add a rule
  when a repository that needs it actually appears.
- **The detector never executes anything.** Reading a project's declared scripts is safe;
  running them is a trust decision. Phase 4.0 — the same boundary that already runs the test
  suite — executes what the detector reports.
- **No auto-generated test commands beyond the conventional ones.** Where a project declares
  its own, that declaration wins.

## Extending it

Add a marker rule only with a real repository shape behind it, and add the test alongside —
`tests/test_detect_profile.py` pins each rule to the situation that motivated it, so the next
reader can see *why* a rule exists and not just what it does.
