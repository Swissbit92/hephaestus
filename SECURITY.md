# Security Policy

How to report a vulnerability in hephaestus, and what to expect in return. This is a single-operator repository; this policy documents the discipline, not a public bug-bounty.

## Supported versions

Plugins version independently (tag namespace `<plugin>-v<x.y.z>`). The latest tag of each plugin is supported; older tags are best-effort.

## Reporting a vulnerability

Single maintainer (Swissbit92). Record security findings as a GitHub issue or in [docs/LESSONS_LEARNED.md](docs/LESSONS_LEARNED.md) with the `security` label. Include affected plugin/commit, reproduction, impact, and suggested fix.

## Scope

- **In scope:** plugins, hooks, and agents in this repository — especially anything that gates or acts on a live system (`kucoin-safety-gate`, domain agents).
- **Out of scope:** third-party dependencies (report upstream); the live trading venues themselves (KuCoin) and their keys (managed outside this repo, in env/launchd).

## Data classification

Highest data classification this repository handles: **Confidential.**

The repo stores no secrets and no financial data — keys live in env/launchd, trading data in MongoDB. But its plugins encode **sensitive operational judgment** (live-venue safety rails, blast-radius rules, domain failure modes) and its hooks can **gate live capital**. That drives the threat assessment in [docs/THREAT_LEVEL.md](docs/THREAT_LEVEL.md).

## Operating rules (the real controls)

- **First-party plugins only.** No third-party marketplace plugins are installed into ecosystem repos (ClawHavoc precedent: marketplace skills weaponized with crypto-wallet infostealers). Any external plugin is reviewed before use.
- **Deterministic gates over instruction.** Live-system safety is enforced by hooks (exit-2 hard-block), never by asking an agent to remember a rule.
- **No secrets in the repo.** Verified by `scripts/check-public-safe.sh` (repurposed as the seam/secret linter).
