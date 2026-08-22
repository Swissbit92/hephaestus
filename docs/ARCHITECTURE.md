---
title: Architecture
status: active
created: 2026-06-28
last_reviewed_on: 2026-08-22
review_in: 6 months
applies_to: hephaestus
ai_summary: "How hephaestus is put together as a multi-plugin Claude Code marketplace: the six plugins and what each is for, the seam rule that keeps generic plugins domain-free, the three layers that hold state (shipped config in the plugin, runtime state outside it, repo-carried ledgers in docs/), and the four executable invariants plus the evidence contract that decide what counts as proof here. Read it before adding a plugin, before adding anything that writes state, or when deciding whether a rule belongs in prose, a test, or an invariant."
---

# Architecture

Reference-style: tables and diagrams, not prose narratives.

## System context

hephaestus is a **catalog**, not a service. Nothing here runs continuously; every component
is invoked by an agent or a developer and exits.

```
Claude Code ──reads──> .claude-plugin/marketplace.json ──lists──> plugins/<name>/
Codex · Pi  ──reads──> plugins/*/skills/<name>/SKILL.md   (skills only — the portable subset)

developer/agent ──runs──> scripts/*.py ──gate──> the repo's own changes
```

Two consumers, deliberately unequal. Claude Code loads a plugin whole — skills, commands,
agents, hooks, MCP servers. Codex and Pi discover **skill directories only**, so slash
commands, subagents, hooks and MCP servers do not travel.
`scripts/install_skills.py` prints that gap rather than letting a skill quietly lose its
hook.

## Components

| Component | Responsibility | Module |
|-----------|----------------|--------|
| Marketplace catalog | Lists every plugin; the entry point Claude Code reads | `.claude-plugin/marketplace.json` |
| **crucible** | Generic, vendor-neutral craft tools (17 skills, `develop` + `curate` commands, the QA agent) | `plugins/crucible/` |
| **forge-unity** | Unity evidence + the `.forge/adapter.json` contract. Engine-specific, operator-free | `plugins/forge-unity/` |
| **sqlite-readonly** | Read-only SQLite MCP server (3-layer read-only, NL→SQL) | `plugins/sqlite-readonly/` |
| **second-brain** | Obsidian inbox processor (suggest-then-confirm; skills only) | `plugins/second-brain/` |
| **deck-builder** | Code-backed `.pptx` builder (python-pptx; outline-approval gate) | `plugins/deck-builder/` |
| **mcp-starter** | Template for packaging a Python MCP server as a plugin | `plugins/mcp-starter/` |
| Release tooling | Per-plugin semver bump, tag, GitHub release | `scripts/release.sh`, `scripts/bump_version.py` |
| Gates | The executable half of the rules below | `scripts/` + `scripts/checks/` |
| Eval harness | Asserts skills behave as their `SKILL.md` claims | `evals/` |
| Test suite | Pure-stdlib pytest over the scripts and harness core | `tests/` |

### The seam

Plugins are tiered, and the boundary is enforced rather than intended:

| Tier | May name | May not name | Enforced by |
|------|----------|--------------|-------------|
| Generic (`crucible`, `sqlite-readonly`, `mcp-starter`, `deck-builder`, `second-brain`) | nothing domain-specific | any engine, employer or product | `tests/test_seam.py` |
| Engine adapter (`forge-unity`) | Unity | any particular game or operator | `tests/test_seam.py` |
| Any file in the repo | — | employer/private-system tokens | `scripts/check-public-safe.sh` |

See [ADR-003](decisions/003-decompose-game-development-support-into-a-growing-crucible-and-one-thin-engine-adapter.md)
for why the engine layer is one thin adapter rather than a plugin set.

## Data

Three storage layers, and the split between the first two is load-bearing — writing runtime
state into the plugin directory puts per-user content inside a versioned generic plugin,
which is the seam violation [ADR-001](decisions/001-consolidated-private-marketplace-and-restricted-agent-factory-architecture.md)
forbids, and plugin updates overwrite that directory anyway.

| Source | Format | Writer | Readers |
|--------|--------|--------|---------|
| `.claude-plugin/marketplace.json` | JSON | maintainer | Claude Code, `validate_manifests.py` |
| `plugins/*/.claude-plugin/plugin.json` | JSON | `release.sh` | Claude Code, `validate_manifests.py` |
| **Shipped config** (`skills/*/state/`) | JSON/YAML | versioned with the plugin; no runtime writes | the skill |
| **Runtime state** (`$CMS_STATE_DIR`, `$CLAUDE_PLUGIN_DATA`, else `~/.claude/cms-state`) | JSON | `cms`, `loop-harness` at run time | the same skill, later runs |
| `docs/predictions.jsonl` | JSONL, append-only | `predictions.py` | `predictions.py list`, `curate` |
| `docs/INVARIANTS.md` | Markdown + `Check:` lines | maintainer | `invariants_run.py` |
| `.crucible/evidence.json` | JSON | maintainer | `evidence_gate.py`, `finish-branch` |
| `.forge/adapter.json` | JSON | the *consuming project*, not this repo | `forge-unity/scripts/adapter.py` |

**Dates never come from mtime.** git neither records nor restores modification times, so
anything derived from `st_mtime` reports every file as new the moment the repo is cloned.
Document age resolves through `plugins/crucible/skills/cms/scripts/doc_age.py` — batched git
committer dates, frontmatter fallback, and silence rather than a guess.

## Key invariants

Standing constraints, each with an executable check. Full text and the
`PROSE → FALSIFIABLE → CHECK → ENFORCED` pipeline: [INVARIANTS.md](INVARIANTS.md).

| Invariant | Check |
|-----------|-------|
| Generic plugins stay domain-free | `scripts/checks/seam_is_clean.sh` |
| A check that could not run is never reported as a pass | `scripts/checks/undetermined_is_not_a_pass.sh` |
| Shipped Python parses on the version the README promises (3.9) | `scripts/checks/python_floor_is_honoured.sh` |
| mtime is never a clock in shipped plugin code | `scripts/checks/mtime_is_never_a_clock.sh` |

Two rules shape all four. **Three-valued outcomes**: every gate distinguishes `pass`,
`fail` and `could-not-check`, because folding the third into the first is how an unverified
change acquires a green tick. And **a check nobody has watched fail is not a check** — each
one above has been validated by reintroducing the defect and observing it go red.

## Evidence contract

What counts as proof here is declared, not assumed. `.crucible/evidence.json` maps changed
paths to the evidence that change requires; `evidence_gate.py` reports the classes a diff
triggers and **never decides whether the evidence exists**. Without it, a repo falls through
to the implied class — "the test suite passes" — which is exactly right in a repo with a
suite and meaningless in one without.

## Cross-repo contracts

Link any shared/canonical contracts this repo depends on (plain links, never `@path`).

hephaestus has none: it is a single repository with no root-level `docs/shared/`, so every
contract it depends on is internal. The scaffolded placeholder that used to sit here pointed
at a file that has never existed — caught by the link check added with ADR-003, which is
exactly the rot that check is for.

## Decisions

Architectural decisions affecting this repo live in [decisions/](decisions/).
