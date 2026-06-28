---
title: Roadmap
status: active
created: 2026-06-28
last_reviewed_on: 2026-06-28
review_in: 3 months
applies_to: hephaestus
---

# Roadmap

Near-term dated items only. Strategic direction: [VISION.md](../VISION.md). Architecture decision: [ADR-001](decisions/001-consolidated-private-marketplace-and-restricted-agent-factory-architecture.md).

The factory is built in value-first phases — each ships standalone value and is independently abandonable. Premortem: this fails if it becomes infrastructure-gardening (meta-work that feels productive while the income engine stalls). Guard: Phase 1 banks live-capital safety + a real eval harness before any speculative orchestration.

## Phase 0 — consolidate + recognize

- [x] Rename marketplace `whetstone` → `hephaestus`; craft plugin → `crucible` (tests green, plugin validate passes).
- [x] Make the GitHub repo private.
- [x] Own docs: VISION, ROADMAP, SECURITY, THREAT_LEVEL, ADR-001.
- [x] Seam linter `test_seam.py` (assert no generic plugin carries domain tokens) + `check-public-safe.sh` reframed as the secret guard + cms `templates/` exclusion (cms check now 0 errors).
- [x] **Cutover to the marketplace** ✅ 2026-06-28 — hephaestus is the single source of truth. Installed `crucible@hephaestus` via the [#17201](https://github.com/anthropics/claude-code/issues/17201) manual-clone workaround (cloned into `~/.claude/plugins/marketplaces/hephaestus`, registered in `known_marketplaces.json`); verified all `crucible:*` artifacts load from the plugin; removed local dupes (`~/.claude/skills/{cms,grill-me}`, nephilim `develop.md`/`qa-gatekeeper.md`) and stripped the global cms hook from `settings.json` (plugin provides it). Kept CRA-domain `discover-strategies.md`. Backups in `~/.claude/_cutover_backup_step3/`. Follow-ups: auto-update via `git -C ~/.claude/plugins/marketplaces/hephaestus pull`; migrate accumulated cms `sync_facts.yaml` into plugin state; prune stale local-cms permission entries.

## Phase 1 — bank the certain value (pays for itself, no role-agents)

- [x] **`eval-first`** ✅ — a **crucible skill** (`plugins/crucible/skills/eval-first/`, sibling to grill-me/cms): baseline-freeze, deterministic-first checks, swap-augmented blind A/B judge (self-grading-guarded), match-or-beat-or-revert. Generic stdlib scripts + templates; 38 tests; crucible 0.3.0→0.4.0. Closes the "no eval for the fabric" gap. (Two upgrades over the source: swap augmentation + pinned-judge-family assertion.)

## Parked / optional (do last)

- [ ] **`kucoin-safety-gate`** plugin (Tier B) — deterministic `PreToolUse` hard-block on Claude-Code-initiated live KuCoin calls (ccxt MCP order tools + bash live-order scripts; **not** production launchd jobs) + `[executed]/[inspected]/[assumed]` tag check. **Parked 2026-06-28 at user request** — optional, revisit when an autonomous loop actually operates near the trading repos.

## Phase 2 — first restricted role-agents — **DEFERRED 2026-06-28** (domain tier premature)

> **Decision (2026-06-28):** the domain-agent tier is **deferred until the trading engine stabilizes.** A guardian only helps once there is a stable contract to guard — and the engine is still being actively built, so its "house rules" (data contracts, conventions, failure modes) are *supposed* to be changing. Freezing them into an agent now would cost more (fighting stale rules) than it returns. This is the premortem working as intended: value-first, don't garden infrastructure while the engine needs building.
>
> **Re-trigger:** revisit when, during real trading work, you repeatedly catch yourself thinking *"I must not break X"* — that repetition is the signal the house rules have solidified enough to write down. Until then: point the **generic tier (`crucible`)** at the engine-building work (it needs no house rules), and keep a cheap **house-rules backlog** — jot each *"don't break X"* moment in a notes file in the trading repo — so codifying the ecosystem ADRs later is transcription, not archaeology.

- [x] Wire `qa-gatekeeper`'s test baseline to read ground truth live ✅ 2026-06-28 — the gate now re-derives the baseline from the branch-point commit (`git merge-base HEAD <target>`, counted in a throwaway worktree) instead of trusting a stated count; regression = fewer passing tests or a newly failing test, added tests are not. Aligned `develop` + `start-branch` baseline wording. crucible 0.5.0→0.5.1. *(Generic gate fix — standalone value, not part of the deferred domain tier.)*
- [ ] *(deferred — see decision above)* **`blast-radius-reviewer`** (read-only; would carry the ecosystem contracts) + **`quant-architect`** (read-only; would carry the quant failure modes). Blocked on stable, written-down house rules.

## Phase 3 — close one loop (safest surface; first loop = CI Sweeper)

Evidence-backed by [research/loop-engineering-2025](research/loop-engineering-2025.md) (deep-research, 2026-06-28). **Architecture: a single-threaded linear agent with shared full-trace context + minimal scaffolding — NOT a persona role-team** (consensus across Cognition + Anthropic; minimal scaffolds match heavy ones on SWE-bench). **Run the unattended sweep on a cheaper model / lower effort, not max-Opus-max-effort** — HAL found higher reasoning effort *reduced* accuracy in most runs, and accuracy↔cost spans ~100×.

- [ ] Borrow the read-only **CI Sweeper** pattern from [`cobusgreyling/loop-engineering`](https://github.com/cobusgreyling/loop-engineering): a `/goal`-style loop watching test suites + launchd logs + the freshness watchdog, triaging failures and drafting fixes **in a worktree only**, **never emit-signals / never live-Mongo / never merge**, surfacing a needs-me report. Read-only diagnosis, no capital path. Monthly-review → remediation handoff is the *second* loop.
- [ ] **Build order (highest-leverage primitives first):**
  1. Loop-driver spine — single-threaded, `LOOP-STATE.md` ledger (note-taking/compaction for context rot) + **budget/turn ceilings + per-run cost log**.
  2. **PreToolUse safety hook** (deterministic, not CLAUDE.md prose) enforcing never-merge / never-leave-worktree / never-touch-live (copy the cms-hook pattern).
  3. Gate drafted fixes through **`eval-first` + `flag-gate`** — *already built in crucible*; this is the trust gate the loop literature requires.
  4. Triage skill: read failure → root-cause → draft-in-worktree → adversarial verify → append to ledger. Add **LLM-aided log inspection** to the needs-me report.
- [ ] **Skip:** persona/role multi-agent teams (net liability — documented). **Defer:** parallel fan-out until there is genuinely independent, shared-context-free work; even then scope it read-only like Anthropic's research fan-out, never a coding crew.

## Phase 4 — conditional orchestration (only if Phases 1–3 prove out)

- [ ] **`sprint-execute`** Dynamic Workflow over genuinely-parallel work, model-mixed per role. Build only where it buys measurable reliability (heed mini-SWE-agent).

## Shipped

See [CHANGELOG.md](../CHANGELOG.md).
