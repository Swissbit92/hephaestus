---
name: eval-first
description: Eval-first development — freeze a baseline, then gate every change on match-or-beat-or-revert. Use when the user wants to evaluate or gate an LLM-backed change, set up evals, compare a candidate against a baseline, run a blind A/B judge, prevent quality regressions, build a "ruler" before optimizing, or asks how to measure whether a change actually helped.
---

You help the user adopt **eval-first development**: never ship a change to an LLM-backed system unless it measurably matches-or-beats the current behavior. The core discipline is *build the ruler before you optimize* — an unmeasured change is a guess, and a model asked to grade its own output will pass it.

## When this applies

Any iterative change to an LLM-backed system where "better" is claimed but not measured: prompt edits, model swaps, RAG/retrieval changes, agent behavior, persona/voice work. If there's no frozen baseline, the first job is to build one — not to make the change.

## The scripts (in this skill's `scripts/`)

All pure-stdlib, dependency-light, with injected `judge_fn`/`embed_fn` so they run headless:

- **`baseline.py`** — `freeze_baseline()` (immutable, one file per version), `compare_to_baseline()` (the match-or-beat gate at the report level; `tolerance` slack).
- **`deterministic.py`** — Layer-1 check registry (`non_empty`, `exact_match`, `regex_match`, `json_has_keys`, `max_length`, `citation_present`, …) + `run_deterministic()`. Cheap, auditable, runs before any judge call.
- **`judge.py`** — blind A/B LLM judge: `build_ab_prompt`, `parse_ab_verdict`, `judge_pairs` (swap-augmented), plus `assert_judge_distinct` (blocks self-grading). `JUDGE_MODEL` is pinned.
- **`ab_harness.py`** — `make_blind_pairs`, `tally` (exact sign test), `verdict` — the match-or-beat-or-revert decision.
- **`reliability.py`** — `pass_hat_k` (pass^k, regression gates), `avg_at_k` (capability), `pass_at_k_estimate`.

Templates in `templates/`: `probes.json.template` (your eval cases) and `eval-config.yaml.template` (thresholds, judge pin, rubric).

## The workflow

1. **Build cases.** Copy `probes.json.template` → `evals/probes.json`. 20–50 cases to start; cover normal use, robustness/edge, and adversarial inputs.
2. **Freeze the baseline FIRST.** Run the *current* system over all cases, score it, `freeze_baseline(path, "legacy", report)`. This is the ruler. Never freeze after the change.
3. **Make the change**, behind a flag/branch (instant revert).
4. **Run the candidate** over the same cases.
5. **Layer 1 — deterministic.** `run_deterministic()` on every output. If it fails structural checks, the candidate loses — no judge call needed (catches 30–60% at ~zero cost).
6. **Layer 3 — blind A/B judge.** For outputs that clear Layer 1, `make_blind_pairs(legacy, candidate)` → `judge_pairs(..., judge_fn)` → `tally` → `verdict`. Judge each pair in **both** orderings (built in) — position bias is real and "ignore order" doesn't work.
7. **Gate.** Apply `verdict` / `compare_to_baseline`:
   - **CANDIDATE BETTER / PARITY** → may ship (flip the flag).
   - **CANDIDATE WORSE** → do NOT ship. Fix, or keep legacy.

## Revert vs. rebase-baseline (decide explicitly, never silently)

- **Revert** the candidate on: any deterministic failure, any regression-suite drop, any safety-check failure.
- **Rebase** (accept a new baseline) only when: the change is an *intentional* behavioral change, blind-validated by a human, and documented in the changelog. A new baseline is never adopted silently.

## Invariants — make these assertions, not conventions

- **Judge family ≠ candidate family** — call `assert_judge_distinct()`; self-grading inflates scores 10–25%.
- **Swap every pairwise comparison** — `judge_pairs` does this; an order-dependent verdict is a tie.
- **Deterministic checks run before the judge** — never spend a judge call on a structural failure.
- **pass^k for regression gates** (every attempt holds), **avg@k / match-or-beat for capability**.
- **Baselines are immutable** — `freeze_baseline` refuses to overwrite; version them alongside code.
- **Run outputs are ephemeral artifacts, not source** — write scored candidate runs and judge dumps to a gitignored results dir (e.g. `evals/results/`). Only the probe set and the frozen baseline belong in version control. Committing timestamped run dumps is how repeated eval-first runs silently turn into repo bloat (MBs of `*.json`/`*.html` nobody reads again).
- **Re-calibrate on any judge model bump** — a silent judge version change shifts scores 3–8 points.

## Anti-patterns

- Optimizing against a metric the model can game (keyword scorers, length-rewarding rubrics). Fix the ruler first.
- Freezing the baseline *after* making the change (you've lost the comparison point).
- Trusting one ordering of an A/B judge (position bias).
- Treating a 1–2% aggregate delta as signal — with n < ~300 and overlapping CIs it's noise.

This skill ships the methodology and the generic scripts; the domain-specific scorer (e.g. an embedding-based attribution metric) stays in the repo that needs it and plugs in via the injected `embed_fn`/`judge_fn`.
