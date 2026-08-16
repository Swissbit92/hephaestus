---
title: Vision
status: active
created: 2026-06-28
last_reviewed_on: 2026-06-28
review_in: 12 months
applies_to: hephaestus
---

# hephaestus — Vision

> **One sentence:** A private Claude Code plugin marketplace that is a coding factory — restricted-agents and deterministic gates that develop the E.E.V.A. ecosystem, where nothing ships until it survives the fire.

## Why this exists

The E.E.V.A. ecosystem (income engine, data pipeline, AI companion, execution layer) is built by one operator across ~5 repos. The **fabric** that develops them — skills, commands, agents, hooks, context discipline — is itself leverage, and it deserves to be a versioned, single-source-of-truth product rather than ad-hoc dotfiles re-explained to every fresh context.

`hephaestus` is the forge (the repo + marketplace identity). `crucible` is the vessel inside it — the generic craft plugin where code is put through trial-by-fire (develop, grill-me, qa-gatekeeper, eval-first) before it's trusted. Hephaestus's domain is the forge; the crucible is where things are proven.

## What it is — and what it deliberately is not

**It is** a factory of **restricted-agents + deterministic gates**: a "role" is a tool-restricted subagent (read-only where it should be) with domain knowledge in its system prompt, gated by deterministic hooks. Parallelism is used only for genuinely independent sub-tasks. The unit of autonomy is the **well-scoped ticket → PR**, with the operator at the epic/merge boundary.

**It is not** a 7-role role-play waterfall (PM → architect → developer → QA → UX). That is the documented anti-pattern: adding sequential roles *degrades* software work (E2EDevBench 53.5% → 27.7% when a design role is added; 39–70% degradation on sequential, shared-state tasks). The SWE-bench leaders are all single-agent loops. The factory's durable value is **verification**, not role theater.

## Three-tier seam (placement law)

| Tier | What | Where |
|------|------|-------|
| **A — generic craft** | domain-free, reusable by anyone: `crucible` bundles every generic artifact type — skills (cms, grill-me, branch lifecycle, skill-craft, + graduated `eval-first` / `flag-gate`), command (`develop`), hook (cms PreToolUse), agent (`qa-gatekeeper`). A generic capability earns its own plugin only if heavy-dep / MCP server / large standalone (sqlite-readonly, deck-builder…). | this marketplace |
| **B — domain factory** | cross-repo, private: `quant-factory` (restricted role-agents + strategy-audit + sprint-execute), `kucoin-safety-gate` | this marketplace |
| **C — per-repo** | un-generalizable specialists | each repo's `.claude/` |

**Graduation:** Tier C → Tier B when 2+ repos need it and it generalizes without distortion. Tier B → Tier A never (domain-bound by definition).

## Non-goals

- **Role-play multi-agent teams.** Verification beats theater on sequential software work.
- **Over-scaffolding.** mini-SWE-agent (~100 lines, >74% SWE-bench) is the reminder: harness complexity is a liability as models improve. Add machinery only where it buys measurable reliability.
- **Cloud-hosted unattended agents over the codebase.** Rejected on the same grounds as the ecosystem's cloud-LLM and OpenClaw rejections (data leakage / supply-chain risk).
- **~~Public distribution.~~ Retired 2026-08-15** — [ADR-002](docs/decisions/002-publish-hephaestus-publicly-retiring-the-private-distribution-non-goal.md). This non-goal assumed the marketplace would carry a Tier-B domain factory whose judgment had to stay private. That tier was never built: all five shipped plugins are Tier-A generic, the seam is enforced by `tests/test_seam.py` rather than asserted, and `scripts/check-public-safe.sh` gates employer-system tokens. The reason for the non-goal was absent from the repo, so the repo is now public — with `checks` a required status check on `main` and the supply-chain risk re-scored upward in [THREAT_LEVEL.md](docs/THREAT_LEVEL.md), since publication *inverts* that risk rather than merely removing a control.
- **Letting documentation become the work.** Docs are lean; the build is the point.

## Origin

Spun out of the E.E.V.A. ecosystem decision [ADR-006](https://github.com/Swissbit92/nephilim) (records the *decision to externalize* the fabric). This repo owns its detailed history from [ADR-001](docs/decisions/001-consolidated-private-marketplace-and-restricted-agent-factory-architecture.md) onward.
