---
title: Consolidated private marketplace and restricted-agent factory architecture
status: Accepted
created: 2026-06-28
last_reviewed_on: 2026-06-28
review_in: 24 months
applies_to: hephaestus
---

# ADR-001: Consolidated private marketplace and restricted-agent factory architecture

## Context

This repo began as **whetstone**, a public Claude Code marketplace of generic craft plugins (cms, grill-me, develop, branch lifecycle, qa-gatekeeper, author-skill) plus sqlite-readonly, mcp-starter, second-brain, deck-builder. The E.E.V.A. ecosystem decision to make the coding fabric a first-class track (ecosystem ADR-006) raised three forces this repo must resolve in its own history:

1. **Marketplace topology.** A two-marketplace split (public-generic + private-domain) is load-bearing on *one* thing only — keeping whetstone public. At solo scale, a single private marketplace is simpler and strictly better: intra-marketplace plugin dependencies are allowed by default, whereas cross-marketplace deps require `allowCrossMarketplaceDependenciesOn` + hand-maintained version pins (a real versioning-hell trap). Private-repo marketplace auth is also currently buggy (GitHub issue #17201).
2. **Factory shape.** The intuitive 7-role waterfall (PM → architect → developer → QA → UX) is the documented anti-pattern: it *degrades* software work (E2EDevBench 53.5% → 27.7% adding a design role; 39–70% degradation on sequential, shared-state tasks). Every SWE-bench leader is a single-agent tool-use loop; mini-SWE-agent (~100 lines) rivals elaborate scaffolds. The durable value is verification, not role theater.
3. **Identity.** "whetstone" conflated repo, marketplace, and plugin name. The factory wants a clear identity with a daily-ergonomic command prefix.

## Decision

1. **Consolidate into one private marketplace.** This repo is private; it hosts both generic-craft and domain-factory plugins, each as a separately-versioned plugin. The seam between generic and domain lives at the **plugin boundary**, enforced by a seam linter and `test_seam.py`. Revisit a two-marketplace split only if a second developer joins.

2. **Identity: `hephaestus` (repo + marketplace) / `crucible` (the generic craft plugin).** Hephaestus is the forge (identity, seen rarely — clone/install). Crucible is the vessel inside it (the daily `/crucible:…` command prefix), and it names the factory's verification soul (grill-me, qa-gatekeeper, eval-first, develop's gated workflow). `whetstone` retires as a name, surviving as the crucible plugin. Domain plugins keep their own names.

3. **Build the factory as restricted-agents + deterministic gates — not role-play.** A "role" is a tool-restricted subagent (read-only where it should be) with domain knowledge in its system prompt, gated by deterministic hooks (`PreToolUse`/`Stop`/`TaskCompleted`, exit 2). Parallelism only for genuinely independent sub-tasks. Unit of autonomy = well-scoped ticket → PR, human at the epic/merge boundary. Explicitly do not build a sequential 7-role waterfall.

4. **Three-tier seam.** Tier A generic craft (crucible + eval-first + flag-gate + safety-middleware) · Tier B domain factory (quant-factory, kucoin-safety-gate) · Tier C per-repo `.claude/`. Graduation: C → B when 2+ repos need it and it generalizes; B → A never.

Phased roadmap in [ROADMAP.md](../ROADMAP.md). Pattern source for Phase 3: `cobusgreyling/loop-engineering`. Rejected: cloud-hosted unattended agents over the codebase (MaxHermes/MiniMax-style) — same security grounds as the ecosystem's cloud-LLM and OpenClaw rejections.

## Status

Accepted (2026-06-28). Derives from ecosystem ADR-006, which records the decision *to externalize* the fabric; this ADR owns the externalized repo's architecture.

## Consequences

**Easier:** a versioned single-source-of-truth fabric with per-plugin rollback (matters for live-capital gates); domain judgment stops being re-explained each session; intra-marketplace dependencies compose cleanly (factory plugins reuse develop, eval-first, safety-middleware) with no cross-marketplace pinning.

**Harder / costs:** making the repo private forfeits whetstone's public-artifact value (accepted — at ~zero external users it charged a sanitization tax); the seam must be policed by linter + discipline (domain leak into a generic plugin is the #1 failure mode — e.g. quant QA checks must go to per-repo hooks or a domain plugin, never into crucible); private-marketplace auth friction (#17201) requires the manual-clone workaround per machine; real opportunity cost vs. object-work, mitigated by value-first phasing.

**Follow-up:** make the GitHub repo private; build `kucoin-safety-gate` + `eval-first` (Phase 1); per-repo `settings.json` version-pins once `kucoin-safety-gate` exists.
