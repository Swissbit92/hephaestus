---
title: "Gate Design — Evidence-Typed Verification (research note)"
status: active
created: 2026-08-01
last_reviewed_on: 2026-08-01
review_in: 6 months
applies_to: hephaestus
ai_summary: "Research note behind evidence-typed verification — why a gate must declare what counts as proof instead of assuming a test suite, and why the verdict is three-valued (pass / fail / could-not-check) rather than binary. Backs .crucible/evidence.json and evidence_gate.py. Read it before changing what the gate accepts, or before folding 'could not check' into either of the other two."
---

# Gate Design — Evidence-Typed Verification

> Research note backing **Phase 5** ([ROADMAP](../ROADMAP.md)). Produced 2026-08-01 from a
> 19-agent fan-out: 14 agents auditing real usage + literature, 5 follow-ups on loop/graph,
> constraint drift, docs-workflow, generic-toolkit design, and frontend prior art.
> **Time-sensitive** — several key sources are 2026 preprints; re-verify before relying on numbers.
> Companion note: [loop-engineering-2025](loop-engineering-2025.md).

## Question

`develop` branches only on **blast radius** (FULL / LIGHT / TRIVIAL). Should it also branch on
**domain** (frontend / backend / data / infra), each with its own mandatory gates — and is the
right upgrade *more graph* (explicit routing) or *better loops* (tighter evidence cycles)?

## Bottom line

**Branch the evidence, not the ceremony.** Keep one spine and one tier ladder; swap in a
**pluggable evidence profile** chosen by marker-file detection. The dominant defect axis is not
frontend-vs-backend but **code-hygiene vs. truth** — today's QA gate checks whether code is
clean, while real defects are dishonest tests, unreal environments, unreached code, and invalid
statistics. And the binding constraint is **enforcement, not specification**: gates already
written in prose are skipped at scale.

## Findings

### A. The gate that exists checks the wrong axis

1. **Zero of ~15 audited production incidents were caught by "all tests pass."** Across ~55
   escaped defects catalogued from the operator's own history, the ranked causes were: tests
   green *because* the mock encoded the bug (13), config/environment/credential (9),
   reachability — built and referenced but never invoked (7), silent failure / swallowed
   exception (7), statistical/methodological error (6), unit/scale mismatch (5), UI/visual (2).
   The one category with **zero escapes** was flag/deploy ordering — the one already gated.
   *Implication: `no orphaned code` is the wrong check; the need is `no unreached code`, which
   static analysis cannot supply.*

2. **Written gates are advisory and get skipped.** In real runs, the Plan agent (Phase 2,
   mandatory for FULL) fired **3 times against 24 FULL classifications**; the docs phase was
   skipped entirely on several FULL runs. Anthropic's own memory docs state the mechanism
   plainly: *"Claude treats [CLAUDE.md and rules] as context, not enforced configuration. To
   block an action regardless of what Claude decides, use a PreToolUse hook instead."*
   **Adding mandatory phases to a document whose mandatory phases are skipped does not add
   verification — it adds text to skip.**

3. **Unreachable nodes.** `develop` wires in 3 of 10 crucible skills. Six have never been
   invoked in any session (`eval-first`, `flag-gate`, `loop-harness`, `act-for-real`,
   `author-skill`, `grill-me`) — and they are the newest and most engineered. The reference
   direction is one-way: those skills point at `develop`; `develop` points back at none. This is
   the single highest-value finding, and graph *thinking* is what surfaced it.

4. **`develop` has no eval.** 61 invocations, zero scenarios in `evals/scenarios.json`. The
   covered set (finish-branch, start-branch, cms, act-for-real) gives false confidence that the
   most-used artifact is safe to change.

### B. Domain routing: narrow the gates, not the workflow

5. **Tool overload is the quantified failure mode, and it argues for narrowing.** Reported
   accuracy collapse from 43% → 2% as a toolset grew 4 → 51; a separate benchmark reports
   13.62% → 43% purely from narrowing the visible tool set. Degradation commonly starts past
   15–20 tools. *(Secondhand from practitioner writeups — directionally strong, not
   independently verified against the primary leaderboards.)*

6. **But forking the whole document backfires.** "Instruction Bleed" (arXiv, 2026-06-26) finds
   cross-module interference **intensifies as conditional branches multiply**, and that
   domain modularization *reduces but does not eliminate* it. IHEval (arXiv 2502.08745) finds
   conflicting-instruction resolution tops out near 48% and does not scale with model size.
   Chroma's context-rot work reports 30–50% non-uniform accuracy drops well before the stated
   limit.

7. **Prior art forks gates, never the spine.** `shinpr/claude-code-workflows` ships
   `dev-workflows` / `-frontend` / `-fullstack` sharing 16 identical agents; the frontend plugin
   adds 5 agents and its own quality-fixer. Anthropic's skill guidance independently prescribes
   the same shape — `reference/frontend.md` vs `reference/backend.md` with **SKILL.md as a
   router, not content**, plus *"avoid fiddly rules tied to one test case and generalize."*

8. **Type-based routing has a documented ceiling.** "The Routing Plateau" (arXiv 2606.07587)
   finds 21 routing methods converge to a narrow band below oracle — routing helps easy cases,
   not hard ones. Treat domain detection as *gate selection*, never as a quality strategy.

### C. What a frontend gate actually mandates

9. **The hard frontend gate is structurally identical to the backend one.** shinpr's
   `quality-fixer-frontend` blocks on: stub/incomplete-implementation scan (first, blocking),
   lint/format, TypeScript **zero type errors**, and tests with a **substance check that rejects
   `expect(true).toBe(true)`**. No screenshot, no visual diff, no a11y scan, no responsive check
   is in the mandatory list.

10. **Visual review is near-universal in existence and almost never blocking.** Across 9
    inspected sources: screenshots 8/9, responsive viewport matrix 5/9, accessibility 4/9,
    pixel-diff 2/9, mandatory e2e **0/9**. Human/advisory review is the final arbiter in ~8/9.
    Two independent sources converged on the same viewport triad: **375 / 768 / 1280**.

11. **A model cannot gate on its own rendering.** "MLLM as a UI Judge" (arXiv 2510.08783;
    9,296 human ratings, 500 participants): 72–77% accuracy within ±1 point on a 7-point scale,
    only **35–38% exact match**; pairwise preference ~60% except on grossly different UIs.
    Design2Code finds domain-authored rubrics beat LLM-authored ones (κ 0.60 vs 0.46).
    **Screenshots are evidence for a human, not a verdict.** The one hard-threshold exception is
    Anthropic's harness-design Evaluator — a *separate* agent armed with Playwright MCP that
    drives the live page and fails the sprint below threshold.

12. **A design *role* is the documented anti-pattern; a design *check* is not.** E2EDevBench
    degrades 53.5% → 27.7% when a design role is added to a sequential team (already recorded in
    [VISION](../../VISION.md)). The distinction that matters is **opinion vs. evidence**, not
    frontend vs. backend.

### D. Loop vs. graph

13. **The taxonomy is sound; the movement is branding.** "Graph engineering" as a discipline
    trended from a 2026-07-18 joke ("Are we still talking loops or did we shift to graphs
    yet?"); explainers and courses followed within a week. DAGs and state machines predate it,
    and LangChain's Harrison Chase reportedly called it *"largely existing orchestration
    rebranded."* The real empirical kernel is Berkeley's MAST taxonomy (14 multi-agent failure
    modes over 150 traces). *(Attribution of the Chase quote is secondhand — unverified.)*

14. **Formalizing flow can make things worse.** A controlled study (arXiv 2604.27891, 2026-05)
    found LangGraph orchestration *increased* failure rates vs. putting the procedure in the
    system prompt (24% vs 11.5%; 17% vs 5%) at 1.2–1.7× the LLM calls. OpenAI announced
    Agent Builder's deprecation in 2026-06 (off-platform 2026-11-30). Guidance across sources:
    *if you can collapse the nodes back into one loop and lose nothing, you should.*

15. **The justified graph work is one edge.** Conditional re-entry — *QA fails the same class
    twice → return to plan with accumulated evidence*, not just back to implement — is real
    practice, not theory. Everything else in a markdown harness lacks the safety nets (reducers,
    checkpointers, validated cycles) that make a real graph runtime worth its ceremony.

16. **Loops must exit on evidence, not confidence.** Anthropic's evaluator-optimizer applies
    *"when we have clear evaluation criteria and iterative refinement provides measurable
    value"*; it differs from retry because a **separate** call returns actionable feedback. A
    fail with no reason is retry, not evaluation. Cited default for code-fix iterations is
    **N=3**; frameworks commonly add a token-budget backstop. Premature completion is now a
    studied failure mode, not folklore, and self-review is a settled negative (self-preference
    bias; the reviewer must be fresh-context).

### E. Constraint decay — why standing requirements evaporate

17. **The failure mode has a name.** **Constraint decay** (arXiv 2605.06445, 2026-05): as
    constraints accumulate, capable models lose ~30 percentage points of compliance from
    baseline to fully-constrained. Prohibitions decay faster than requirements — omission
    compliance falls 73% → 33% between turn 5 and turn 16 (arXiv 2604.20911). Compaction does
    **not** reliably reset drift: across 20 compaction events in real Claude Code sessions it
    increased as often as it decreased (ContextEcho, arXiv 2605.24279). *(All three are recent
    preprints — directionally credible, not settled.)*

18. **One-time requirements and standing constraints have opposite lifespans and must not share
    an artifact.** A feature spec dies at merge; "mobile-first" must outlive every task. Filing
    the second in the first is why standing requirements appear to be forgotten.

19. **The durable fix is executable, not prose.** Ranked by durability: automated test/lint >
    PreToolUse/PostToolUse hook > path-scoped rules > CLAUDE.md restatement > gate-time
    checklist re-read. EARS / Given-When-Then matter as the **conversion step** — they force a
    vague constraint into falsifiable form ("mobile-first" → *at viewport ≤768px, no horizontal
    scroll*) that can then become an assertion. *No head-to-head study of prose-only vs.
    test-encoded requirement survival was found; the argument is structural, not measured.*

### F. Generalizing without overfitting

20. **A single operator's defect mix is not the population's.** Frontend-only is 5.6% of
    developers but full-stack is 27%, and 85% of frontend developers also do backend (JetBrains
    2025, n=24,534). Defect distribution is **domain-dependent**: a TypeScript-ecosystem study
    puts Tooling/Config at 27.8% and UI at 12.5%; an application-heavy OSS corpus puts UI bugs
    at 38.2%. A backend-only history structurally cannot produce the bug classes that dominate
    UI-bearing projects.

21. **Detect, don't configure and don't guess.** nx, Turborepo, semantic-release and scaffolders
    all resolve project type from marker files (`package.json`, `pyproject.toml`, `go.mod`,
    `Cargo.toml`), preferring framework markers over packaging markers — and **skip rather than
    guess when detection fails.** Pair with convention-over-configuration defaults and honest
    README scoping ("defaults validated on X; other profiles unvalidated").

### G. Where ceremony belongs

22. **Workflow-vs-skill has a usable criterion.** A capability earns multi-phase ceremony when it
    is **(a) hard to reverse, (b) branches on external system state, or (c) has a real cost if
    skipped** beyond a doc going stale. Otherwise it stays a skill. In current Claude Code,
    commands and skills have effectively merged, so a subcommand-bearing skill is already the
    modern form of a multi-step capability — there is no higher tier to graduate into. Process
    gates also ratchet: once added they are rarely removed even after they stop paying.

23. **`cms` is the exemplar, not the patient.** It already carries what `develop` lacks:
    deterministic scripts, a PreToolUse hook, tiered Error/Warning (*"a gate that blocks on a
    regenerable artifact is one people learn to bypass"*), content-hash staleness, and
    creation-time enforcement. Documentation drift tooling in the wild (drift-vscode,
    driftcheck) is early-stage and not worth adopting yet.

## Prioritized recommendations

**Build first:**

1. **Freeze the ruler before moving it** — `develop` + `qa-gatekeeper` eval scenarios and a
   baseline. Changing the most-invoked artifact with zero coverage is the exact blast radius
   `eval-first` exists for. *(Finding 4.)*
2. **Truth gates in `qa-gatekeeper`** — does this test assert the *right value* or merely that a
   value came back · is this code *reached* from a live entry point · are exceptions swallowed.
   Prompt-level, generic, targets ~27 of 55 catalogued defects. *(Findings 1, 9.)*
3. **Evidence-typed Phase 4 via marker detection** — `references/evidence-*.md`, SKILL.md as
   router; hard gate same shape per domain, visual output as evidence never verdict; no marker →
   skip, don't guess. *(Findings 5–11, 20–21.)*
4. **Invariants mechanism** — rules → EARS → executable check; the doc is a *pointer to the
   check*, never the enforcement. *(Findings 17–19.)*
5. **One graph edge + a bounded loop** — backtrack-to-plan on repeated same-class QA failure;
   cap fix attempts (~N=3); require QA feedback to be actionable. *(Findings 15–16.)*
6. **Wire the orphaned skills** into `develop` so the reachable set matches the built set.
   *(Finding 3.)*

**Deliberately skip:** a UX-gatekeeper persona; screenshot self-critique as a pass/fail gate;
mandatory e2e; forking `develop` into per-domain variants; promoting `cms` to a phased workflow.

## Open questions

- Does evidence-typed routing measurably beat one generic gate, on the frozen `develop` eval?
- What is the real false-skip rate of marker-file detection on mixed repos?
- Do truth-gate prompts raise the REJECT rate (currently ~5% over 21 runs) without raising false
  alarms?
- Minimum viable form of the "is this code reached" check that does not require a live trace.
- Whether the backtrack-to-plan edge fires often enough to justify existing.

## Key sources

- Anthropic — *Building Effective Agents* — https://www.anthropic.com/engineering/building-effective-agents
- Anthropic — *Harness design for long-running application development* (2026-03-24)
- Anthropic — *Effective context engineering for AI agents* — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Anthropic — Claude Code memory & hooks docs — https://code.claude.com/docs/en/memory · https://code.claude.com/docs/en/hooks
- Anthropic — Agent Skills best practices — https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- Constraint decay — arXiv 2605.06445 · Omission/commission decay — arXiv 2604.20911 · ContextEcho — arXiv 2605.24279
- Instruction Bleed (2026-06-26) · IHEval — arXiv 2502.08745 · Chroma *Context Rot* — https://research.trychroma.com/context-rot
- MLLM as a UI Judge — arXiv 2510.08783 · Design2Code — arXiv 2403.03163
- Orchestration-vs-prompt controlled study — arXiv 2604.27891 · The Routing Plateau — arXiv 2606.07587
- MAST multi-agent failure taxonomy (Berkeley, Cemri et al., 2025)
- shinpr/claude-code-workflows — https://github.com/shinpr/claude-code-workflows
- Stack Overflow Developer Survey 2025 — https://survey.stackoverflow.co/2025/developers/
- JetBrains State of Developer Ecosystem 2025 — https://blog.jetbrains.com/research/2025/10/state-of-developer-ecosystem-2025/
- Factory.ai — *Using Linters to Direct Agents* — https://factory.ai/news/using-linters-to-direct-agents
