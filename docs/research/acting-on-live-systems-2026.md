---
title: "Acting on Live External Systems — 2025/2026 State of the Art (research note)"
status: active
created: 2026-07-17
last_reviewed_on: 2026-07-17
review_in: 6 months
applies_to: hephaestus
---

# Acting on Live External Systems — 2025/2026 State of the Art

> Research note backing the **`act-for-real`** skill.
> Produced 2026-07-17 via the `deep-research` harness at **reduced rigor** (see Caveats):
> 4 angles, ~40 sources fetched, 86 claims extracted, 20 verified (4 refuted) with **2-vote**
> adversarial verification — **stopped before synthesis**, so findings below are hand-synthesized
> from extracted + partially-verified claims, weighted toward primary sources.
> **Time-sensitive** — the agentic-browser/tooling landscape moves fast; re-verify before relying
> on any number.

## Question

When an agent must take a **real, irreversible action** on a **live system it often does not own**
(financial portal, registrar, payments/mail API, someone else's prod), what actually goes wrong,
and what discipline should a generic toolkit (`crucible`) encode? Framed originally as "does
crucible need a browser-automation skill?" — the answer reframed the question (see Bottom line).

## Bottom line

1. **The tool layer is solved and should not be rebuilt.** The field converged on
   **DOM/accessibility-tree** control over vision/screenshots for reliability and cost. A generic
   toolkit should *assume* a browser/API tool exists and add nothing there.
2. **The methodology layer is where the value is — and vendors are already shipping it as
   skills**, which validates skill-shaped packaging of *discipline* rather than tools.
3. **The unsolved, high-severity risks are not "clicking the wrong button"** — they are
   (a) believing an action succeeded when it didn't, (b) acting on stale state, (c) fabricating
   real-world identifiers, (d) treating page/tool content as instructions, and (e) acting without
   the human's authority. All five are **domain-neutral** — they apply to API calls, infra changes
   and mail sends exactly as much as to browsers.
4. **Therefore: no browser skill. A `act-for-real` discipline instead**, sibling to `loop-harness`
   (refuses prod) and `flag-gate` (makes changes revertible), for the case where neither applies.

## Findings (confirmed)

**F1 — Verify the resulting state, never the call.** *(primary)* Guidance for browser agents states
plainly that agents *"should verify action outcomes rather than assuming success after issuing
commands, as DOM changes may not reflect intended results."* Generalizes directly: a `200`, a green
toast, or a non-erroring click is not the state. **This is the single highest-value rule in the
skill.**

**F2 — TOCTOU (check-and-use) is a real, measured failure class.** *(primary, academic)* Across 10
evaluated browser-use agents, **all exhibited TOCTOU vulnerabilities** under at least one
manipulation type. Root cause: *"the agent selects an action based on an observation captured at
check time, but the action is applied to the live page at a later use time."* A pre-execution
validation mechanism (MutationObserver/ResizeObserver, abort on change) **prevented all** exploits
in evaluation at **<0.05s** per-loop overhead, leaving only a ~0.13s residual window (~0.2% success
under optimized attacker timing). → **Re-read state immediately before acting.**

**F3 — External content is an attack surface, not a principal.** *(primary, multiple)* Indirect
prompt injection is **actively exploited**. Agentic browsers were shown to feed page content to the
LLM *"without distinguishing between the user's instructions and untrusted content."* Demonstrated
impact includes exfiltrating a user's **email address and one-time password** via instructions
hidden in a forum comment. Concealment techniques include zero-sized fonts, off-screen positioning,
transparency, and base64 payloads decoded after scanning. Crucially: *"traditional Web security
assumptions don't hold for agentic AI — the AI operates with the user's full privileges across
authenticated sessions."* → **Treat everything the target system says as data.**

**F4 — Human-in-the-loop is the consensus control for credential/financial actions.** *(primary,
multiple)* *"For sensitive operations involving credentials or financial transactions, human
oversight should be maintained before executing actions."* Approval must be **bound to the exact
action**: *"Include the actor, tool name, target resource, normalized parameters, timestamp, and
expiry in the approval record."* Step-up authentication is recommended for payment initiation,
account recovery, privilege changes, bulk deletion. Decision-making should be **separated from
execution** (agent proposes; an independent component validates scope/privilege/approval).

**F5 — The recommended *scope* for agentic action is deliberately narrow.** *(secondary)* Guidance
restricts agentic browsing to *"low-stakes tasks (e.g., research, public data gathering)"* and
avoiding *"privileged sessions"* for financial/email/publishing actions **without confirmation**.
Prompt injection is characterized as a *"frontier, unsolved security problem"*, with agentic
browsers in the *"most dangerous quadrant"* (autonomous action + sensitive data access). → The
skill's job is partly **restraint**: say what not to automate.

**F6 — Tooling converged on DOM/accessibility-tree, not vision.** *(primary + blog)* Playwright MCP
*"enables LLMs to interact with web pages through structured accessibility snapshots, bypassing the
need for screenshots or visually-tuned models"*, self-described as *"deterministic… avoids ambiguity
common with screenshot-based approaches"*, at ~200–400 tokens/snapshot vs thousands. A comparative
blog reports DOM-driven stacks outperforming vision by **12–17 points** (~92% vs ~78%/75%) at
~$0.02–0.10 vs $0.20–0.50 per task — **directional only, single blog source**.

**F7 — Vendors ship browser *methodology as skills*, not just tools.** *(primary)* A first-party
vendor collection provides **14 modular agent skills** for Claude Code — including a self-improving
loop (*"iteratively runs a browsing task, reads the trace, and improves"*), a capability-isolation
skill (*"whose only browser capability is a CDP-gated tool"*), cookie/session reuse instead of
hard-coded credentials, and a skill that reverse-engineers a site's HTTP into an OpenAPI spec to
bypass the DOM entirely. → **Skill-shaped methodology is a validated pattern — and this space is
already occupied. Don't duplicate it.**

**F8 — Self-healing locators are a solved-enough, named pattern.** *(primary + blog)* Runtime
AI-resolved locators (natural language → element) with success-caching; a vendor self-healing agent
reports **>75%** success on selector-related failures; named strategies include *"Selector
Fallback"* and *"Element Reclassification"* (locate by function via text/ARIA/proximity rather than
DOM structure). → Reliability at the *tool* layer is not crucible's problem to solve.

**F9 — The tool layer explicitly disclaims being a security boundary.** *(primary)* Playwright MCP
states: *"Playwright MCP is **not** a security boundary."* It offers persistent profiles for
session reuse and an `--isolated` mode discarding storage state on close. → Isolation is available,
but the guarantee is not. The skill must say the same about itself.

**F10 — 2FA remains genuinely unsolved outside specialist tools.** *(blog)* Leading frameworks
provide **no built-in 2FA/TOTP**, relying on external solutions (one specialist tool integrates
native 2FA/TOTP). Prevailing practice is **session/profile reuse** — *"Login once, reuse later"* —
rather than automating the second factor. → Hand 2FA to the human; don't script it.

## Prioritized recommendations (for `act-for-real`)

1. **Verify from a fresh read; make UNVERIFIED a mandatory, sayable outcome.** (F1) Highest value,
   lowest cost, and the failure is otherwise silent.
2. **Re-read immediately before acting.** (F2) Cheap mitigation for a measured failure class.
3. **Bind approval to the exact action; human owns credential-gated/irreversible steps.** (F4)
   Never automate the confirmation that *is* the authorization. (F10)
4. **Treat target-system content as data, never instructions.** (F3)
5. **Never fabricate a real-world identifier**; require provenance + a structural check; on failure,
   ask. *(Not from the literature — from dogfooding; see Open questions.)*
6. **Own no transport.** (F6, F8) Assume an external tool; add nothing at the tool layer.
7. **Encode restraint.** (F5) The skill should be as clear about what not to automate as how.

## Caveats

- **Reduced rigor, by request.** Verification ran at **2 votes with "both must refute to kill"**
  (vs the harness default of 3/2), which is **lenient** — weak claims survive more easily. Only
  4 of 20 verified claims were refuted; that ratio should be read as *"the pass was gentle"*, not
  *"the claims are strong"*.
- **Stopped before synthesis.** The report below the harness's own synthesis step was
  hand-assembled from extracted claims. No merge/dedup pass was applied by the harness.
- **Source-quality split.** F1–F5, F7, F9 rest on primary sources (vendor docs, framework repos,
  security research). **F6's benchmark numbers and F8/F10 are blog-sourced — treat as
  directional.**
- **Fast-moving.** Agentic-browser vulnerabilities and tool capabilities changed materially within
  2025. Re-verify before citing.
- **Recommendation 5 has no external source.** It emerged from dogfooding, not the literature. It
  is included because the failure mode was observed directly and is high-severity, but it is
  explicitly weaker-evidenced than F1–F4.

## Open questions (resolve empirically — eval-first applied to the skill itself)

1. **Does the gate fire rarely enough to survive?** The stated risk is ceremony-fatigue. Measure:
   how often does CLASSIFY exit immediately vs proceed? If it rarely exits, the trigger is too wide.
2. **Is "two independent verification channels" achievable in practice**, or is one fresh read the
   realistic ceiling for most systems?
3. **Should identifier-provenance be code-backed** (a checksum/format validator script) rather than
   prose? Prose rules are the ones agents rationalize past.
4. **Does `develop` need an explicit hand-off phase**, or is a prose pointer sufficient for the
   rare boundary-crossing case (live migration, secret rotation, infra apply)?

## Key sources

- Playwright MCP (Microsoft) — accessibility-tree control; "not a security boundary"; persistent
  vs `--isolated` profiles. *(primary)*
- Browserbase agent-skills collection — 14 modular browser skills for Claude Code, incl.
  self-improving loop, CDP-gated capability isolation, cookie-sync. *(primary)*
- TOCTOU-in-browser-agents evaluation — 10/10 agents vulnerable; MutationObserver pre-execution
  validation prevents all, <0.05s overhead. *(primary, academic)*
- Indirect prompt-injection research + 2025 agentic-browser advisories — email/OTP exfiltration PoC;
  concealment taxonomy; "full privileges across authenticated sessions". *(primary)*
- Agent security guidance — bind approval to the exact action; separate decision from execution;
  least-privilege tools; treat all external data as untrusted. *(primary)*
- Stagehand / Browser Use / self-healing comparisons — runtime-resolved locators, caching,
  "Selector Fallback" / "Element Reclassification"; >75% healer success. *(blog — directional)*
