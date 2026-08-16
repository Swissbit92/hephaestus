---
title: "Loop Engineering — 2024/2025 State of the Art (research note)"
status: active
created: 2026-06-28
last_reviewed_on: 2026-06-28
review_in: 6 months
applies_to: hephaestus
---

# Loop Engineering — 2024/2025 State of the Art

> Research note backing the **Phase 3 CI Sweeper** design ([ROADMAP](../ROADMAP.md)).
> Produced 2026-06-28 via the `deep-research` harness: 22 sources, 25 claims verified
> (24 confirmed, 1 killed), 8 synthesized findings, 3-vote adversarial verification.
> **Time-sensitive** — benchmark leaderboards drift; re-verify numbers before relying on them.

## Question

What works in semi-autonomous / autonomous **coding loops**, and which primitives should a
generic Claude Code toolkit (`crucible`) expose first — for a read-only **CI Sweeper** loop
(watches tests + job logs + freshness, triages failures, drafts fixes **in a worktree only**,
never merges, never touches production, surfaces a "needs-me" report)?

## Bottom line

Default to a **single-threaded, linear agent with shared full-trace context and minimal
scaffolding.** Treat multi-agent fan-out as a special-case tool for **breadth-first,
read-only exploration** — never as the backbone of a coding/triage loop. The highest-leverage
primitives to build first are **not** persona role-teams but: (1) hard budget/turn ceilings +
cost auditing, (2) a context-compaction / LOOP-STATE ledger, (3) worktree-only non-merging
isolation behind an eval/verification gate, (4) LLM-aided log inspection for the "needs-me"
report.

## Findings (confirmed)

1. **Single-threaded linear agents with full shared context are the proven default; parallel
   teams are fragile** — subagents make conflicting implicit decisions without shared traces
   and can't reliably recombine. Reliability needs *full agent traces*, not just messages.
   — Cognition, *Don't Build Multi-Agents*; Anthropic, *Building Effective Agents*. (3-0)

2. **Multi-agent fan-out wins ONLY on breadth-first, read-only research** (Anthropic's
   orchestrator-worker beat single-agent Opus by 90.2% on a research eval) — but is a poor fit
   for coding: ~15× the tokens, needs high task value, and coding has few truly parallelizable
   subtasks. Anthropic explicitly excludes "most coding tasks." — Anthropic, *Multi-agent
   research system*. (3-0) **Do not cite the 90.2% to justify a coding fan-out.**

3. **Minimal scaffolding matches or beats elaborate scaffolding on coding benchmarks.**
   mini-swe-agent (~100 lines, bash-only, linear history, no tool-calling interface) scores
   **>74%** on SWE-bench Verified; Live-SWE-agent + Opus 4.5 hits **79.2%** (authors' own
   leaderboard); OpenHands' heavy scaffold beats mini-swe-agent by **<1 point**. — mini-swe-agent
   repo; live-swe-agent.github.io; codesota. (3-0)

4. **Elaborate hand-crafted scaffolds & persona role-teams are a net liability for a solo dev** —
   performance becomes over-dependent on prompt tuning, human intervention obscures true
   capability, pipelines are costly to maintain. Add complexity only when simpler demonstrably
   fails; prefer **workflows** (predefined code paths) for well-defined tasks, reserve
   **autonomous agents** for open-ended ones. — Lita (arXiv 2509.25873); Anthropic. (3-0)

5. **The scaffold materially changes outcomes; accuracy correlates with cost (~100× spread);
   and higher reasoning effort REDUCED accuracy in the majority of HAL runs.** A purpose-built
   single-agent scaffold (SWE-Agent + Sonnet 4.5) tops SWE-bench Verified Mini at 72%, beating
   a generic generalist agent across tiers. — HAL (arXiv 2510.11977; hal.cs.princeton.edu). (3-0)
   **Implication: don't run the unattended sweep on max model / max effort — cheaper is often
   better AND far cheaper.**

6. **Context is a finite "attention budget" ("context rot"); long loops need explicit context
   management.** Three primitives: (a) **compaction** (summarize + reinitiate), (b) **note-taking
   / agentic memory** (persist notes outside context — *this is the LOOP-STATE ledger*),
   (c) **sub-agents** (explore → return condensed summary). Cognition favors a dedicated
   compression model over parallel splitting for long-horizon coding. — Anthropic, *Effective
   context engineering*; Cognition. (3-0)

7. **LLM-aided log inspection surfaces failures aggregate scores hide** (e.g. agents searching
   for the benchmark on HuggingFace instead of solving the task; misusing credit cards).
   Behavioral log auditing is a first-class trust primitive — essential for a trustworthy
   "needs-me" report and to catch out-of-scope / reward-hacking actions. — HAL. (3-0)

8. **PreToolUse hooks are the deterministic guard, not CLAUDE.md.** A PreToolUse hook always
   runs (exit 2 → blocked) regardless of model reasoning; CLAUDE.md instructions the LLM may
   ignore. Read-only / non-merge / never-touch-production must be **hooks**. — paddo.dev;
   Anthropic, *Claude Code sandboxing*. (verified)

## Prioritized recommendations (for the read-only CI Sweeper)

**Build first** (each a direct application of a verified finding):
1. **Budget/turn ceilings + per-run cost auditing** ← 15× token cost + ~100× cost spread.
2. **Context-compaction + LOOP-STATE ledger** (note-taking / agentic memory) ← context rot;
   enables loop-until-dry without context overflow.
3. **Worktree-only, non-merging isolation behind an eval/verification gate** ← workflows for
   well-defined tasks; *crucible already has this* via `eval-first` (match-or-beat-or-revert)
   + `flag-gate` (default-OFF) — extend to gate drafted fixes.
4. **LLM-aided log/behavioral inspection** feeding the "needs-me" report.

**Deliberately skip:** elaborate persona / role multi-agent teams.
**Defer:** parallel fan-out — and when it arrives, scope it like Anthropic's read-only research
fan-out (independent, shared-context-free, results not recombined), never a coding crew.
**Keep** the loop a single-threaded linear agent with shared full traces.

## Caveats

- **Self-reported numbers:** Live-SWE's 79.2% / "leading open-source" is the authors' own
  leaderboard; Anthropic's 90.2% and 15× are first-party. Treat as magnitude, not gospel.
- **Benchmark ≠ production:** SWE-bench resolution rates do **not** directly predict CI-triage
  performance; research-fan-out gains do **not** transfer to coding.
- **Lita** (2-1 vote) is a single unreplicated preprint and only "competitive" (trails OpenHands
  ~5-10% on flagship SWE-bench Verified) — read as "minimal is competitive AND cheaper," not
  "minimal wins."
- **Refuted (1-2, do not rely on):** the "Agent Complexity Law" (that the simple-vs-complex gap
  vanishes as models improve).

## Open questions (resolve empirically — eval-first applied to the loop itself)

- Best **stop-conditions** for loop-until-dry (no-new-failures vs. ledger-converged vs.
  budget-exhausted) and their false-stop rates.
- Whether an **adversarial second-pass critic** before surfacing a draft fix is worth the tokens
  (given higher reasoning effort sometimes *hurt* accuracy).
- Minimum **shared context** a future coding fan-out needs to avoid recombination failure.
- The ideal **LOOP-STATE ledger schema** (decisions / events / open hypotheses) for compaction recall.
- False-positive/negative rate and cost of LLM-aided log inspection as a guardrail.

## Key sources

- Cognition — *Don't Build Multi-Agents* — https://cognition.com/blog/dont-build-multi-agents
- Anthropic — *Multi-agent research system* — https://www.anthropic.com/engineering/multi-agent-research-system
- Anthropic — *Building Effective Agents* — https://www.anthropic.com/research/building-effective-agents
- Anthropic — *Effective context engineering for AI agents* — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic — *Effective harnesses for long-running agents* — https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- Anthropic — *Claude Code sandboxing* — https://www.anthropic.com/engineering/claude-code-sandboxing
- mini-swe-agent — https://github.com/SWE-agent/mini-swe-agent
- Live-SWE-agent — https://live-swe-agent.github.io/
- HAL (Princeton) — arXiv 2510.11977 · https://hal.cs.princeton.edu/swebench_verified_mini
- Lita — arXiv 2509.25873
- Claude Code hooks as guardrails — https://paddo.dev/blog/claude-code-hooks-guardrails/
