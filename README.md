# hephaestus

[![CI](https://github.com/Swissbit92/hephaestus/actions/workflows/ci.yml/badge.svg)](https://github.com/Swissbit92/hephaestus/actions/workflows/ci.yml)

A small workshop of [Claude Code](https://code.claude.com) plugins to keep your craft sharp.

## Plugins in this marketplace

| Plugin | What it is |
|--------|------------|
| **crucible** | Generic craft tools: `cms`, `grill-me`, `develop`, `start-branch`, `finish-branch`, `qa-gatekeeper` (detailed below). |
| **sqlite-readonly** | Zero-config read-only SQLite MCP server — query any local `.db` safely (3-layer read-only, schema introspection, NL→SQL). See [its README](plugins/sqlite-readonly/README.md). |
| **mcp-starter** | A minimal, working template for packaging a Python MCP server as a plugin (userConfig injection, inline servers, uv, first-run hook, `/setup`). See [its README](plugins/mcp-starter/README.md). |
| **second-brain** | Obsidian inbox processor — proposes tags/links/filing/actions per note, applies only what you approve (suggest-then-confirm). See [its README](plugins/second-brain/README.md). |
| **deck-builder** | Build polished `.pptx` decks from source material — code-backed (named layout methods, never hand-rolled geometry), with an outline-approval gate. See [its README](plugins/deck-builder/README.md). |

## crucible plugin

| Tool | Type | What it does |
|------|------|--------------|
| **cms** | skill + hook | Context Management System — standardizes docs across repos for AI-agent token efficiency. Frontmatter linting, ADR scaffolding, drift detection, staleness-based archival. Enforces frontmatter on `docs/*.md` edits via a `PreToolUse` hook. |
| **grill-me** | skill | Adversarial sparring partner — stress-tests a decision/plan before you commit (assumption audit, pre-mortem, outside view, falsifiable tripwires). |
| **develop** | command | A structured development workflow — classify → research → architect → isolate → implement → QA → docs → completion → integrate, with gates between phases. |
| **start-branch** | skill | Isolate work before implementing — detects the repo's integration target (never hardcoded), picks a plain branch vs. git worktree, names it Conventional-Branch style, records a clean test baseline, confirms in one line. Used by `develop`'s ISOLATE phase (2.5). |
| **finish-branch** | skill | Close out a branch/worktree safely — gates on tests, offers merge / PR / keep / discard, PR-by-default for deploy branches, cleans up without losing unmerged work (`-d` never `-D`, informed discard). Used by `develop`'s INTEGRATE phase (6.5). |
| **qa-gatekeeper** | agent | Skeptical QA gate used by `develop`'s Phase 4 — verifies stated changes, hunts bugs/orphaned code, runs tests, and returns PASS / CONDITIONAL PASS / REJECT. |
| **author-skill** | skill | Guide + scaffolder for writing a high-quality skill/plugin — lays out the authoring patterns (with real exemplars) and creates a pre-structured `SKILL.md` via `scripts/new_skill.py`. User-invoked. |

## Install

```
/plugin marketplace add Swissbit92/hephaestus
/plugin install crucible@hephaestus            # generic craft tools
/plugin install sqlite-readonly@hephaestus      # read-only SQLite MCP server (needs uv)
/plugin install mcp-starter@hephaestus          # MCP-plugin template
```

Then the tools are namespaced under the plugin:

- `/crucible:cms` — run any CMS command (see the skill for subcommands)
- `/crucible:grill-me` — start a grilling session
- `/crucible:develop` — run the development workflow
- `/crucible:start-branch` · `/crucible:finish-branch` — isolate / integrate work safely

`cms` and `grill-me` are also model-invoked: Claude triggers them automatically when their description matches what you're doing (editing docs, validating a decision).

## What's portable, what to adapt

- **grill-me** — fully generic, works out of the box.
- **cms** — generic engine. The `PreToolUse` hook gates `docs/*.md` edits. By
  default it scopes to the **current working directory**; set `CMS_ROOTS`
  (OS-path-separated list) to gate a fixed set of repos instead. Drift facts
  live in `state/sync_facts.yaml` and ship empty — add your own.
- **develop** — the workflow *structure* is generic; the per-repo specifics
  (critical-logic paths, test commands, alignment questions) are marked `<...>`
  for you to fill in. Its Phase 4 uses the bundled **qa-gatekeeper** agent; its
  optional ISOLATE/INTEGRATE phases call **start-branch**/**finish-branch**.
- **start-branch / finish-branch** — fully generic. They **detect** the host
  repo's branch model (reading its CLAUDE.md, then git) and never hardcode a
  target branch or naming convention, so they work unchanged across `dev→prod`,
  main-release, trunk-based, and GitHub-Flow repos.
- **qa-gatekeeper** — generic; infers the project's test command from the repo.
  Augment its quality standards with your repo's CLAUDE.md.

## cms state & persistence

CMS keeps a little state (CLAUDE.md size history, drift facts). Plugin updates
overwrite the cached plugin dir, so state resolves in this order:

1. `CMS_STATE_DIR` (explicit override)
2. `${CLAUDE_PLUGIN_DATA}/cms-state` (persists across plugin updates)
3. `<plugin>/skills/cms/state/` (local fallback)

## Requirements

- Claude Code with plugin support
- Python 3.9+ on `PATH` as `python3` (cms scripts are pure stdlib — no pip installs)

## Layout

```
hephaestus/
├── .claude-plugin/marketplace.json     # marketplace catalog (lists all plugins)
├── scripts/                            # release.sh · bump_version.py · check-public-safe.sh
├── tests/                              # pytest suite
└── plugins/crucible/
    ├── .claude-plugin/plugin.json      # plugin manifest + cms hook
    ├── skills/
    │   ├── cms/                         # SKILL.md + scripts/ + templates/ + state/
    │   ├── grill-me/SKILL.md
    │   ├── start-branch/SKILL.md
    │   └── finish-branch/SKILL.md
    ├── commands/develop.md
    └── agents/qa-gatekeeper.md
```

## Releasing

The `version` in `plugin.json` is what triggers updates for installed users —
pushing commits without bumping it does nothing for them. Use the helper, which
keeps the manifest version and git tag in lockstep:

```bash
scripts/release.sh <plugin> patch            # 0.1.0 -> 0.1.1
scripts/release.sh <plugin> minor            # 0.1.0 -> 0.2.0
scripts/release.sh <plugin> major            # 0.1.0 -> 1.0.0
scripts/release.sh <plugin> 1.2.3            # explicit version
scripts/release.sh <plugin> patch --dry-run  # preview, change nothing
```

`<plugin>` is a directory under `plugins/` (e.g. `crucible`). Each plugin versions
independently under its own tag namespace `<plugin>-v<x.y.z>`. The script refuses to run
unless you're on `main` with a clean tree, validates the plugin, then commits, tags,
pushes, and creates a GitHub release with notes drawn from that plugin's commits since its
last tag. The version math lives in `scripts/bump_version.py` (unit-tested).

## License

MIT — see [LICENSE](LICENSE).
