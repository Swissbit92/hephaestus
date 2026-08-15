---
title: Publish hephaestus publicly, retiring the private-distribution non-goal
status: Accepted
created: 2026-08-15
last_reviewed_on: 2026-08-15
review_in: 24 months
applies_to: hephaestus
---

# ADR-002: Publish hephaestus publicly, retiring the private-distribution non-goal

## Context

[VISION.md](../../VISION.md) lists **"Public distribution"** as an explicit non-goal:

> This repo is private; the generic tools were once public (whetstone) but the factory carries domain judgment that stays private.

That reasoning was sound when written. Two facts have since overtaken it.

**The domain tier was never built.** ADR-001 planned a Tier-B `quant-factory` and `kucoin-safety-gate` carrying domain judgment. Neither exists. All five shipped plugins — `crucible`, `deck-builder`, `mcp-starter`, `second-brain`, `sqlite-readonly` — are Tier-A generic. The thing the non-goal protects is not in the repo.

**The seam is enforced, not merely asserted.** `tests/test_seam.py` fails the build if a domain token reaches a generic plugin, and `scripts/check-public-safe.sh` fails on employer-system tokens. The clean-room claim is mechanically verified rather than remembered.

Two controls do genuinely depend on privacy, and this ADR must not pretend otherwise. [THREAT_LEVEL.md](../THREAT_LEVEL.md) credits "repo private" as an active mitigation for **information disclosure**, and again for **A08 supply-chain** alongside the ClawHavoc precedent (1,184+ marketplace skills weaponised with crypto-wallet infostealers). Publishing removes the first and inverts the second: a public marketplace stops being reachable only by its owner and becomes something anyone can fork, typosquat, or file a malicious pull request against.

### Evidence gathered before proposing this

| Check | Scope | Result |
|---|---|---|
| Token-shaped secret scan | 517 blobs, all refs, full history | 0 hits |
| `check-public-safe.sh` (employer IP) | working tree | pass |
| Employer tokens in history | 517 blobs | 3 hits — all versions of the guard script matching its own PATTERN; benign |
| Personal filesystem paths | working tree | 0 |
| Domain nouns inside `plugins/` | working tree | 0 |
| `tests/test_seam.py` | all generic plugins | pass |
| Full suite | repo | green |

Residual, and deliberately not scrubbed: roughly twenty mentions of the operator's own projects across five narrative documents (VISION, SECURITY, ROADMAP, THREAT_LEVEL, ADR-001). These name no credential, address, strategy parameter, or capital figure. They explain *why the tooling is shaped as it is*, which makes it more credible rather than less — and nineteen commits of history carry earlier versions regardless, so scrubbing the working tree would buy nothing short of a history rewrite.

## Decision

**Publish the repository publicly**, and retire "Public distribution" as a non-goal.

1. `VISION.md` drops the non-goal and points here.
2. `THREAT_LEVEL.md` stops crediting "repo private" as a mitigation. Information disclosure falls back to `check-public-safe.sh` plus the secret scan as the operative controls; A08 supply-chain is **re-scored upward** — a public marketplace is a documented attack target, and "first-party plugins only" plus branch protection become the controls that carry the weight.
3. Documentation asserting a visibility state is rewritten **visibility-neutral** wherever the statement is not load-bearing, so no document is false in either state.
4. `check-public-safe.sh` and `test_seam.py` are promoted from hygiene to **release gates** — they are what makes the clean-room claim true rather than remembered.
5. Support expectations are stated plainly in the README: shared as-is, no support promised. Publishing invites issues and pull requests; a single-operator workshop should say so rather than disappoint quietly.

## Status

**Accepted — executed 2026-08-15.** The repository is public at
<https://github.com/Swissbit92/hephaestus>.

Order of operations, deliberately: every prerequisite first, the one-way door last.

1. Pre-flight re-run immediately before the flip — public-safety guard, full suite, no
   personal paths, LICENSE present, clean tree, in sync with origin, and a fresh secret
   sweep over **526 blobs across all refs: 0 hits**.
2. Repository visibility flipped to public.
3. Branch protection applied on `main` within the same minute: `checks` required and
   **strict** (a branch must be current with `main` before merging), force-pushes and
   branch deletion disabled.

Both release gates were already wired into the `checks` job before publication —
`pytest -q` (which carries `tests/test_seam.py`) and `scripts/check-public-safe.sh` — so
requiring `checks` promotes them from hygiene to enforcement, exactly as this ADR asks.
Branch protection could not be applied while the repo was private (GitHub returns 403 and
requires Pro or a public repo), which is why it follows the flip rather than preceding it.

`enforce_admins` is deliberately **false**: a single operator locking themselves out of
their own `main` buys nothing, and the honest control here is the required status check,
not a self-imposed gate that would just be toggled off under pressure.

## Consequences

**Easier.** The generic craft tooling becomes usable, and improvable, by people other than its author. The seam tests gain the strongest available enforcement: public scrutiny. The tooling stops being invisible work.

**Harder.** Every future commit is public by default, so the discipline that currently protects a private repo must hold permanently and on the first attempt. Issues and pull requests arrive from strangers. A08 supply-chain risk rises materially, making branch protection and review-before-merge load-bearing rather than optional. The operator's association with their own projects becomes searchable — already true via other public repos, but consolidated here.

**Follow-up.** Wire `check-public-safe.sh` and `test_seam.py` into CI as required checks if they are not already; enable branch protection on `main` before flipping; decide whether to submit to the Anthropic community marketplace, which applies its own automated safety screening.
