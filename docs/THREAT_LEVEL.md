---
title: Threat Level
status: active
created: 2026-06-28
last_reviewed_on: 2026-06-28
review_in: 6 months
applies_to: hephaestus
threat_level: Medium
---

# Threat Level — hephaestus

A living threat model. `threat_level: Medium` because this marketplace will hold plugins (hooks/agents) that **gate and act on live financial systems**, and a plugin marketplace is a documented supply-chain target.

## Current assessment

| Field | Value |
|-------|-------|
| Threat level | Medium |
| Owner | Swissbit92 |
| Last reviewed | 2026-06-28 |

## Trust boundaries

```
[ LLM-generated tool calls ]              [ live systems ]
[ retrieved/RAG content     ] → [ hephaestus plugins ] → [ KuCoin · MongoDB · git ]
[ (future) external plugins  ]      (hooks · agents)
                                          ▲
                                  trust boundary: nothing reaches a live
                                  system except through a deterministic gate
```

Untrusted: anything an LLM emits, anything retrieved, any non-first-party plugin code. Trusted: first-party reviewed plugins + deterministic hooks.

## STRIDE

| Threat | Applies? | Control / mitigation | Status |
|--------|----------|----------------------|--------|
| **S**poofing | Low | single-operator, GitHub auth | n/a |
| **T**ampering | **Yes** | live-system actions only via deterministic `PreToolUse` hooks (`kucoin-safety-gate`) | Phase 1 |
| **R**epudiation | Low | git history; `[executed]/[inspected]/[assumed]` claim tagging | partial |
| **I**nformation disclosure | **Yes** | repo private; no secrets committed; `check-public-safe.sh` linter | active |
| **D**enial of service | **Yes** | runaway loops bounded by `--max-turns`/budget ceilings + `loop-cost`/`loop-audit` | Phase 3 |
| **E**levation of privilege | **Yes** | agent issuing a live order w/o confirmation → hard-blocked by safety gate; injection-guard blocks RAG-triggered tool calls | Phase 1 (`safety-middleware`, `kucoin-safety-gate`) |

## Top risks

- **A03 Injection** — prompt-injection via retrieved content triggering a tool call → `safety-middleware` injection-guard (trust hierarchy system > user > RAG; retrieved content informs, never triggers).
- **A08 Software/data integrity (supply chain)** — a malicious/compromised plugin or skill (ClawHavoc: 1,184+ marketplace skills weaponized with crypto-wallet infostealers). Mitigation: **first-party plugins only**, repo private, review before adding any external plugin.
- **EoP via live order** — the headline risk. `kucoin-safety-gate` (deterministic `PreToolUse` hard-block) is the irreducible control; built in Phase 1.

## Residual risks

- Private-marketplace auth bug ([#17201](https://github.com/anthropics/claude-code/issues/17201)) forces a manual-clone workaround per machine — operational friction, not a security hole.

## Escalation

If threat level would rise to **Critical** (e.g. a live order bypassed a gate, or a third-party plugin was found compromised): freeze the affected plugin (pin previous tag / disable), record a post-incident note in [LESSONS_LEARNED.md](LESSONS_LEARNED.md), and audit every repo's `settings.json` for the affected plugin version.
