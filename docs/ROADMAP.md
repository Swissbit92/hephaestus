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
- [ ] **Cutover to the marketplace** — make hephaestus the single source of truth and remove local duplicates. Gated on the private-marketplace install being verified working (auth bug [#17201](https://github.com/anthropics/claude-code/issues/17201) → manual-clone workaround). Steps: (1) `/plugin marketplace add Swissbit92/hephaestus` + install `crucible`; (2) repoint the nephilim cms `PreToolUse` hook from local `~/.claude/skills/cms/scripts/hook.py` → the crucible plugin; (3) remove now-duplicated locals — `~/.claude/skills/{cms,grill-me}`, `~/nephilim/.claude/commands/develop.md`, `~/nephilim/.claude/agents/qa-gatekeeper.md`, `start-branch`/`finish-branch`/`author-skill`; (4) verify `/crucible:*` commands + the hook fire from the plugin. Best done after Phase 1 so `eval-first` is in the marketplace and cut over in the same pass.

## Phase 1 — bank the certain value (pays for itself, no role-agents)

- [ ] **`eval-first`** plugin (Tier A) — extract from nephilim ADR-005: baseline-freeze, match-or-beat-or-revert, blind-judge. **Primary Phase-1 deliverable** (generic, no live-system risk; closes the "no eval for the fabric" gap).

## Parked / optional (do last)

- [ ] **`kucoin-safety-gate`** plugin (Tier B) — deterministic `PreToolUse` hard-block on Claude-Code-initiated live KuCoin calls (ccxt MCP order tools + bash live-order scripts; **not** production launchd jobs) + `[executed]/[inspected]/[assumed]` tag check. **Parked 2026-06-28 at user request** — optional, revisit when an autonomous loop actually operates near the trading repos.

## Phase 2 — first restricted role-agents

- [ ] **`blast-radius-reviewer`** (read-only; carries the ecosystem ADR-001/002/003/004) + **`quant-architect`** (read-only).
- [ ] Wire `qa-gatekeeper`'s test baseline to read ground truth live (kill the stale-baseline false-alarm → loop-trustworthy gate).

## Phase 3 — close one loop (safest surface; first loop = CI Sweeper)

- [ ] Borrow the read-only **CI Sweeper** pattern from [`cobusgreyling/loop-engineering`](https://github.com/cobusgreyling/loop-engineering): a `/goal`-style loop watching test suites + launchd logs + the freshness watchdog, triaging failures and drafting fixes **in a worktree only** — `LOOP-STATE.md` ledger + `--max-turns`/budget ceilings (model: that repo's `loop-cost`/`loop-audit`), **never emit-signals / never live-Mongo / never merge**, surfacing a needs-me report. Read-only diagnosis, no capital path. Monthly-review → remediation handoff is the *second* loop.

## Phase 4 — conditional orchestration (only if Phases 1–3 prove out)

- [ ] **`sprint-execute`** Dynamic Workflow over genuinely-parallel work, model-mixed per role. Build only where it buys measurable reliability (heed mini-SWE-agent).

## Shipped

See [CHANGELOG.md](../CHANGELOG.md).
