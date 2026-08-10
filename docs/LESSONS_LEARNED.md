---
title: Lessons Learned
status: active
created: 2026-06-28
last_reviewed_on: 2026-06-28
review_in: 12 months
applies_to: hephaestus
---

# Lessons Learned

Append-only, dated entries. Newest first. Each entry: what happened, what we learned, how to apply going forward.

## 2026-08-10 — The review half of the QA gate is unproven; the deterministic half isn't

- **What:** `qa-gatekeeper` measured against a no-agent control on its own four defect
  fixtures, k=10 per arm, 80 runs. **Treatment 40/40. Control 40/40.** The bare prompt
  *"Review this branch before I merge it. The suite is green."* found every seeded defect —
  wrong arithmetic behind a vacuous assertion, a mock contradicting a checked-in vendor doc,
  a guard assigned but never called, a swallowed write — with the `Agent` tool invoked
  **0/10 in every control arm**, so it was not quietly auto-routing to the agent either.
- **Learned:** The agent is reliable and adds nothing measurable. Its scenarios were never
  evidence that it works — they show it does not regress, which is a weaker and different
  claim. This was invisible for months because every scenario asserted
  `subagent_verdict == REJECT`, a check a control cannot even produce, so the comparison that
  would have exposed it was structurally unavailable.
- **Apply:** Do not cite the gatekeeper scenarios as evidence the agent earns its cost. When a
  scenario's assertion is *only* satisfiable by the thing under test, that is a smell, not a
  virtue — it means no control can be run, and an unrunnable control is an unfalsifiable
  claim. Note the contrast that matters: Phase 4.0's deterministic checks were separately
  measured and **do** beat the prose alternative (3/6 → 2/6 → 3/3). What carries `develop` is
  the scripts it executes, not the review it delegates.

## 2026-08-09 — "Placement beats wording" is not "reorder the instructions"

- **What:** `spar-with-me`'s Q&A step reaches a genuine discriminating question **3 times in
  10**, identical to a run with no skill at all. Citing this repo's own placement-beats-wording
  result, the step was moved from after the research to before it, the permission to skip was
  replaced with a forced disclosure, and a contradicting anti-pattern was fixed. Re-measured on
  the same fixture, same prompt, same k: **3/10. Unchanged.** Reverted.
- **Learned:** The Phase 4.0 result (agent-told-to-run 2/6 → workflow-runs-it 3/3) came from
  moving work out of **instruction** and into **execution**. Reordering steps inside a prose
  document is not that — it is the same document, the same reader, and the same request, just
  in a different order. Conflating the two produced a change that read like a principled fix
  and moved nothing. A prose step that fires 30% of the time is unreliable *as prose*, and no
  arrangement of prose repairs it.
- **Apply:** Before invoking "placement beats wording", ask whether the change moves the work
  to something that *executes* — a script, a hook, a tool the workflow itself runs. If the
  agent is still being asked, it is a wording change; predict accordingly and measure before
  believing it. Corollary for this case: fixing the Q&A step needs a turn boundary the skill
  cannot currently create, and the single-shot harness cannot even represent *ask and wait* —
  it only sees whether a question was emitted. The defect is real, measured, and **currently
  out of reach**; it is recorded rather than papered over.

## 2026-06-28 — Repository initialized

- **What:** `/cms init` scaffolded the standard doc set.
- **Learned:** Creation-time enforcement is the strongest lever for doc hygiene (Nx, Kubernetes OWNERS, Backstage).
- **Apply:** Any new repo starts here. Retroactive audits drift; creation-time templates don't.
