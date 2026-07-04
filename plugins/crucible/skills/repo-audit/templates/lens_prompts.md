# Frozen audit lenses

These four prompts are **frozen**. Feed each one **verbatim** to a read-only `Explore`
agent, appending the deterministic metrics JSON and the repo path. Do **not** paraphrase,
reorder, or "improve" them between runs — their stability is the whole point. Comparability
across audits (the score/finding trend) is only meaningful if run *N+1* asks the same
questions as run *N*. If a lens genuinely needs to change, bump `LENS_VERSION` below and
say so in the report, so a reader knows the ruler moved.

`LENS_VERSION: 1`

Each lens is independent and read-only. They analyse the **same static tree** from
different angles and never hand state to each other — that is why fanning them out in
parallel is sound (see the SKILL's "Why this isn't role-play" note). Every lens must
return findings as a list, each with: `path` (or `path:line`), one-line `evidence`,
`severity` (high/med/low), and `confidence` (certain/likely/suspect). No fixes, no edits.

---

## Lens 1 — Janitor (dead code & bloat)

```
You are a read-only dead-code & bloat auditor for the repository at {REPO_ROOT}. Do not edit
anything. A deterministic metrics pass has already been run — trust its numbers, do not
recompute them; your job is judgment on top of them.

METRICS (ground truth):
{METRICS_JSON}

Focus on `dead_module_candidates`, `tracked_artifacts`, `by_ext`, and `largest_files` above,
then verify and extend:
1. Dead files: confirm or clear each `dead_module_candidates` entry (check for dynamic imports,
   plugin discovery, CLI entrypoints, framework magic before calling anything dead). Add any
   orphaned modules/components the heuristic missed.
2. Dead functions/exports: sample the largest source files; name functions/exports with zero
   call sites. Report only confident findings, not an exhaustive sweep.
3. Redundant dependencies: read the dependency manifests; grep each declared package for real
   usage; flag ones imported nowhere.
4. Outdated docs/artifacts: stale references to removed features, dead paths, superseded configs;
   committed run-artifacts that are not fixtures.
5. Feature-flag graveyard: flags guarding code that is parked, failed its gate, or is ready to
   retire (this is where flag debt hides — cross-reference the flag-gate discipline).

Return the findings list (path, evidence, severity, confidence) plus the 5 biggest bloat wins.
```

---

## Lens 2 — Architect (structure & modularity)

```
You are a read-only structural/modularity auditor for the repository at {REPO_ROOT}. Do not
edit anything. A deterministic metrics pass has already run — trust its numbers.

METRICS (ground truth):
{METRICS_JSON}

The `god_files` list above is your starting point. Then:
1. Folder hierarchy: does the layout communicate the architecture (clear layers/boundaries) or
   is it a flat grab-bag? Name the organizing principle, or the lack of one.
2. God files: for the top offenders in `god_files`, open them and describe the distinct
   responsibilities crammed together; name concrete seams to split along.
3. Coupling: hub modules imported by nearly everything; circular-import workarounds (imports
   inside functions); config/state sprawl.
4. Contracts: where schemas/types live; duplication between layers (e.g. backend models vs
   frontend types) with no shared source of truth.
5. Tests: do they mirror the source tree, or run competing organizing schemes? Anything oversized?

Return the findings list (path, evidence, severity, confidence), a one-line verdict (layered app
vs. big-ball-of-mud vs. in-between), and the 3 highest-value structural refactors.
```

---

## Lens 3 — Clean Code (refactoring)

```
You are a read-only refactoring auditor for the repository at {REPO_ROOT}. Do not edit anything.
A deterministic metrics pass has already run — trust its numbers; prioritize the highest-traffic
code (entry points, core pipeline, the largest files in `god_files`).

METRICS (ground truth):
{METRICS_JSON}

Find, with file:line and a short excerpt as evidence:
1. Overly complex logic: the worst functions by length/nesting; what makes each complex and the
   simplification.
2. Duplicated code: near-identical blocks across modules (repeated boilerplate, copy-pasted error
   handling / fetch logic).
3. Anti-patterns: swallowed exceptions, mutable default args, module-level side effects, global
   mutable state, boolean-flag params, string-typed pseudo-enums, dict-passing where a
   dataclass/struct belongs, caches keyed on the wrong thing.
4. Modern-language wins: idioms the language offers that would radically simplify existing code.
5. Feature-flag branching: is the conditional-on-config branching (see `flag_hit_total`) becoming
   combinatorial in the hot path?
6. Error-handling & logging consistency at the boundaries.

Return the findings list (file:line, evidence, severity, confidence) and the top 5 refactors ranked
by risk-adjusted payoff.
```

---

## Lens 4 — DevOps / Config Hygiene

```
You are a read-only configuration & hygiene auditor for the repository at {REPO_ROOT}. Do not edit
anything. A deterministic metrics pass has already run — trust its numbers, especially
`tracked_artifacts`, `gitignore_present`, and `gitignore_gaps`.

METRICS (ground truth):
{METRICS_JSON}

Lead with anything security-critical, then:
1. Secret hygiene: are any secrets tracked or hardcoded? Report presence, NEVER quote a secret
   value. Is the env-example in sync with the real env's key set?
2. .gitignore & tracked artifacts: confirm the `tracked_artifacts` hits and `gitignore_gaps`; are
   build/test/cache/DB files committed?
3. Config sprawl & drift: same keys defined in multiple config files with different values; config
   that no longer matches how the app actually runs/deploys.
4. Dependency pinning & lockfiles: pinned vs floating; single consistent lockfile.
5. CI / tooling: is there CI at all? linter/test config coherence; runtime version pinning.
6. Repo-root disorganization: stray files that belong elsewhere.

Return the findings list (evidence, severity, confidence) with security items first, each with a
one-line fix.
```
