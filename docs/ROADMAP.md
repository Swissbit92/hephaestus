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

## Phase 2 — first restricted role-agents

- [ ] **`blast-radius-reviewer`** (read-only; carries the ecosystem ADR-001/002/003/004) + **`quant-architect`** (read-only).
- [x] Wire `qa-gatekeeper`'s test baseline to read ground truth live ✅ 2026-06-28 — the gate now re-derives the baseline from the branch-point commit (`git merge-base HEAD <target>`, counted in a throwaway worktree) instead of trusting a stated count; regression = fewer passing tests or a newly failing test, added tests are not. Aligned `develop` + `start-branch` baseline wording. crucible 0.5.0→0.5.1.

## Phase 3 — close one loop (safest surface; first loop = CI Sweeper)

- [ ] Borrow the read-only **CI Sweeper** pattern from [`cobusgreyling/loop-engineering`](https://github.com/cobusgreyling/loop-engineering): a `/goal`-style loop watching test suites + launchd logs + the freshness watchdog, triaging failures and drafting fixes **in a worktree only** — `LOOP-STATE.md` ledger + `--max-turns`/budget ceilings (model: that repo's `loop-cost`/`loop-audit`), **never emit-signals / never live-Mongo / never merge**, surfacing a needs-me report. Read-only diagnosis, no capital path. Monthly-review → remediation handoff is the *second* loop.

## Phase 4 — conditional orchestration (only if Phases 1–3 prove out)

- [ ] **`sprint-execute`** Dynamic Workflow over genuinely-parallel work, model-mixed per role. Build only where it buys measurable reliability (heed mini-SWE-agent).

## Shipped

See [CHANGELOG.md](../CHANGELOG.md).
